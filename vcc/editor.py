"""Montaje del Short: clip en vertical, rótulos, voz en off y subtítulos."""
import subprocess
from pathlib import Path

from .subs import escribir_ass, transcribir
from .voice import duracion, tts

RAIZ = Path(__file__).resolve().parent.parent
# Fuente Inter: la del sistema (paquete fonts-inter) o, si no, la carpeta fonts/ del proyecto
_SISTEMA = Path("/usr/share/fonts/opentype/inter")
FUENTES = _SISTEMA if (_SISTEMA / "InterDisplay-Black.otf").exists() else RAIZ / "fonts"
F_TITULO = FUENTES / "InterDisplay-Black.otf"
F_TEXTO = FUENTES / "Inter-ExtraBold.otf"

W, H, FPS = 1080, 1920, 30
VID_Y = 600          # el vídeo horizontal ocupa de y=600 a y=1320
VID_H = 720

AMARILLO = "0xFFD700"
MORADO_TWITCH = "0x9146FF"

NUMEROS = {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"}


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def _esc(txt: str) -> str:
    """Escapa texto para drawtext de ffmpeg."""
    return (txt.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")
            .replace("%", "\\%").replace(",", "\\,"))


def montar_segmento(clip, salida, numero, streamer, cabecera, frase_voz, cfg, trabajo: Path):
    """Un tramo del Short: un clip con su número, crédito, voz y subtítulos."""
    trabajo.mkdir(parents=True, exist_ok=True)
    base = trabajo / Path(salida).stem

    # 1) Recorte: nos quedamos con los últimos N segundos (el momento suele estar al final del clip)
    dur_clip = duracion(clip)
    max_s = cfg["segundos_max_por_clip"]
    inicio = max(0.0, dur_clip - max_s)
    dur = min(dur_clip, max_s)

    # 2) Voz en off
    voz_mp3 = base.with_suffix(".voz.mp3")
    dur_voz = tts(frase_voz, voz_mp3, cfg)

    # 3) Audio final: juego bajado mientras habla la voz + voz encima
    audio = base.with_suffix(".audio.wav")
    fin_ducking = dur_voz + 0.5
    _run([
        "ffmpeg", "-y", "-ss", f"{inicio:.2f}", "-t", f"{dur:.2f}", "-i", str(clip), "-i", str(voz_mp3),
        "-filter_complex",
        f"[0:a]aresample=48000,volume='if(lt(t,{fin_ducking:.2f}),0.28,1)':eval=frame[juego];"
        f"[1:a]aresample=48000,adelay=250|250,volume=1.6[voz];"
        f"[juego][voz]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
        "-map", "[a]", "-ac", "2", str(audio),
    ])

    # 4) Subtítulos de todo lo que se oye (streamer + voz)
    ass = base.with_suffix(".ass")
    escribir_ass(transcribir(audio, cfg["modelo_subtitulos"], cfg["idioma"]), ass)

    # 5) Vídeo vertical
    credito = _esc(f"twitch.tv/{streamer}")
    num = _esc(f"#{numero}")
    cab = _esc(cabecera.upper())
    ass_esc = str(ass).replace("\\", "/").replace(":", "\\:")
    fontsdir = str(FUENTES).replace(":", "\\:")
    vf = (
        f"[0:v]fps={FPS},split[a][b];"
        # fondo: el mismo clip, ampliado, desenfocado y oscurecido
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.18[bg];"
        # primer plano: el clip a 720 px de alto, recortado a lo ancho
        f"[b]scale=-2:{VID_H},crop={W}:{VID_H}[fg];"
        f"[bg][fg]overlay=0:{VID_Y}[v1];"
        # cabecera
        f"[v1]drawtext=fontfile='{F_TITULO}':text='{cab}':fontsize=58:fontcolor=white:"
        f"x=(w-text_w)/2:y={VID_Y - 110}:borderw=5:bordercolor=black@0.85[v2];"
        # número grande
        f"[v2]drawtext=fontfile='{F_TITULO}':text='{num}':fontsize=190:fontcolor={AMARILLO}:"
        f"x=(w-text_w)/2:y={VID_Y - 330}:borderw=9:bordercolor=black[v3];"
        # crédito del streamer en una pastilla morada
        f"[v3]drawtext=fontfile='{F_TEXTO}':text='{credito}':fontsize=44:fontcolor=white:"
        f"x=(w-text_w)/2:y={VID_Y + VID_H + 34}:box=1:boxcolor={MORADO_TWITCH}:boxborderw=18[v4];"
        # subtítulos
        f"[v4]ass='{ass_esc}':fontsdir='{fontsdir}'[v]"
    )
    _run([
        "ffmpeg", "-y", "-ss", f"{inicio:.2f}", "-t", f"{dur:.2f}", "-i", str(clip), "-i", str(audio),
        "-filter_complex", vf, "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-r", str(FPS), "-shortest", str(salida),
    ])
    return salida


def unir(segmentos, salida, trabajo: Path):
    lista = trabajo / "lista.txt"
    lista.write_text("".join(f"file '{Path(s).resolve()}'\n" for s in segmentos))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
          "-movflags", "+faststart", str(salida)])
    return salida


def montar_top(clips, salida, cfg, trabajo: Path):
    """clips: lista de dicts {ruta, streamer} ordenados de MÁS a MENOS visto.
    Se presentan en cuenta atrás: #3, #2, #1."""
    n = len(clips)
    orden = list(reversed(clips))
    segmentos = []
    for i, c in enumerate(orden):
        numero = n - i
        if i == 0:
            frase = f"Lo más loco de GTA 6 hoy. Número {NUMEROS.get(numero, numero)}."
        elif numero == 1:
            frase = "Y el número uno."
        else:
            frase = f"Número {NUMEROS.get(numero, numero)}."
        seg = trabajo / f"seg_{numero}.mp4"
        montar_segmento(c["ruta"], seg, numero, c["streamer"], "Lo más loco de GTA VI hoy",
                        frase, cfg, trabajo)
        segmentos.append(seg)
    return unir(segmentos, salida, trabajo)


def montar_unico(clip, salida, streamer, cfg, trabajo: Path):
    """Short limpio de un solo clip: el clip entero, grande y centrado, con subtítulos
    de lo que se dice y el nombre del streamer. Sin voz en off ni títulos."""
    trabajo.mkdir(parents=True, exist_ok=True)
    base = trabajo / Path(salida).stem
    dur = min(duracion(clip), cfg.get("segundos_max_unico", 59))

    audio = base.with_suffix(".audio.wav")
    _run(["ffmpeg", "-y", "-t", f"{dur:.2f}", "-i", str(clip), "-vn", "-ac", "2", "-ar", "48000", str(audio)])
    ass = base.with_suffix(".ass")
    palabras = transcribir(audio, cfg["modelo_subtitulos"], cfg["idioma"])
    # si después de la última frase hay más de 4 s sin hablar, se corta ahí: los Shorts que se alargan pierden gente
    if palabras and dur - palabras[-1][1] > 4:
        dur = max(10.0, palabras[-1][1] + 1.5)
    escribir_ass(palabras, ass, margen_v=UNICO_SUBS_MARGEN)

    credito = _esc(f"twitch.tv/{streamer}")
    ass_esc = str(ass).replace("\\", "/").replace(":", "\\:")
    fontsdir = str(FUENTES).replace(":", "\\:")
    vf = (
        f"[0:v]fps={FPS},split[a][b];"
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.22[bg];"
        f"[b]scale={W}:-2[fg];"
        f"[bg][fg]overlay=0:(H-h)/2[v1];"
        f"[v1]drawtext=fontfile='{F_TEXTO}':text='{credito}':fontsize=40:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-{W}*9/16)/2-96:box=1:boxcolor={MORADO_TWITCH}:boxborderw=16[v2];"
        f"[v2]ass='{ass_esc}':fontsdir='{fontsdir}'[v]"
    )
    _run([
        "ffmpeg", "-y", "-t", f"{dur:.2f}", "-i", str(clip),
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-r", str(FPS), "-movflags", "+faststart", str(salida),
    ])
    return salida


# subtítulos justo debajo del vídeo (el vídeo 16:9 ocupa y=656..1264)
UNICO_SUBS_MARGEN = 1920 - 1264 - 150
