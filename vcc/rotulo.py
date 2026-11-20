"""Rótulo con el titular del vídeo en la parte de arriba del Short.
Las palabras entre *asteriscos* van en amarillo."""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from vcc.editor import F_TITULO

W, H = 1080, 1920
AMARILLO = (255, 208, 40)
Y_CENTRO = 178          # centro vertical del rótulo (zona libre encima del vídeo)
ANCHO_MAX = 960


def _lineas(palabras, fuente):
    """Reparte las palabras en como mucho 2 líneas que quepan en ANCHO_MAX."""
    esp = fuente.getlength(" ")
    lineas, actual, ancho = [], [], 0
    for p in palabras:
        w = fuente.getlength(p.replace("*", ""))
        if actual and ancho + esp + w > ANCHO_MAX:
            lineas.append(actual)
            actual, ancho = [], 0
        ancho += (esp if actual else 0) + w
        actual.append(p)
    if actual:
        lineas.append(actual)
    return lineas


def png_rotulo(texto, destino):
    palabras = texto.split()
    tam = 84
    while True:
        f = ImageFont.truetype(str(F_TITULO), tam)
        lineas = _lineas(palabras, f)
        if len(lineas) <= 2 or tam <= 52:
            break
        tam -= 4
    alto_l = tam * 1.12
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y0 = Y_CENTRO - alto_l * len(lineas) / 2
    # placa oscura detrás para que se lea sobre cualquier fondo
    placa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(placa).rounded_rectangle([40, y0 - 30, W - 40, y0 + alto_l * len(lineas) + 30], 34, fill=(8, 6, 20, 175))
    capa.alpha_composite(placa)
    sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    texto_l = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds, dt = ImageDraw.Draw(sombra), ImageDraw.Draw(texto_l)
    esp = f.getlength(" ")
    for i, linea in enumerate(lineas):
        total = sum(f.getlength(p.replace("*", "")) for p in linea) + esp * (len(linea) - 1)
        x = (W - total) / 2
        y = y0 + i * alto_l
        for p in linea:
            limpio = p.replace("*", "")
            col = AMARILLO if p.startswith("*") else (255, 255, 255)
            ds.text((x, y + 6), limpio, font=f, fill=(0, 0, 0, 255))
            dt.text((x, y), limpio, font=f, fill=(*col, 255), stroke_width=3, stroke_fill=(10, 4, 24, 255))
            x += f.getlength(limpio) + esp
    capa.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(8)))
    capa.alpha_composite(texto_l)
    capa.save(destino)
    return destino


def rotular(video, texto, salida, trabajo, quitar=None):
    """quitar: lista de tramos (inicio, fin) en segundos a recortar (pantallas de carga, menús)."""
    png = png_rotulo(texto, Path(trabajo) / (Path(salida).stem + "-rotulo.png"))
    pre, v, a, audio = "", "[0:v]", "0:a", ["-c:a", "copy"]
    if quitar:
        cond = "+".join(f"between(t,{x},{y})" for x, y in quitar)
        pre = (f"[0:v]select='not({cond})',setpts=N/FRAME_RATE/TB[vc];"
               f"[0:a]aselect='not({cond})',asetpts=N/SR/TB[ac];")
        v, a, audio = "[vc]", "[ac]", ["-c:a", "aac", "-b:a", "160k"]
    # el rótulo entra con un pequeño fundido en los primeros 0,25 s
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-loop", "1", "-i", str(png),
                    "-filter_complex", pre + f"[1]format=rgba,fade=in:st=0:d=0.25:alpha=1[r];{v}[r]overlay=0:0:shortest=1[vo]",
                    "-map", "[vo]", "-map", a,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    *audio, "-movflags", "+faststart", str(salida)], check=True)
    return salida
