"""Shorts de datos v2 (Vice Clips): tipografía cinética, datos animados, fondo de juego, SFX.
Uso: python3 render2.py guiones.json [id] [--frames]"""
import json
import math
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H, FPS = 1080, 1920, 30
AQUI = Path(__file__).parent
SALIDA = AQUI / "salida"
SALIDA.mkdir(exist_ok=True)

F_BLACK = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
F_XB = "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"
F_SEMI = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
F_MED = "/usr/share/fonts/opentype/inter/InterDisplay-Medium.otf"

ROSA = (255, 46, 136)
CIAN = (0, 224, 255)
AMARILLO = (255, 208, 40)
VERDE = (60, 240, 140)
ROJO = (255, 60, 70)
BLANCO = (255, 255, 255)
GRIS = (170, 170, 190)
COLORES = {"rosa": ROSA, "cian": CIAN, "amarillo": AMARILLO, "verde": VERDE, "rojo": ROJO, "blanco": BLANCO}


@lru_cache(None)
def fuente(ruta, tam):
    return ImageFont.truetype(ruta, int(tam))


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_back(x):
    x = clamp(x)
    c1, c3 = 1.9, 2.9
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


# ------------------------------------------------------------------ capas fijas
def _vignette():
    y, x = np.mgrid[0:H, 0:W]
    d = np.sqrt(((x - W / 2) / (W * 0.75)) ** 2 + ((y - H / 2) / (H * 0.62)) ** 2)
    a = np.clip((d - 0.35) * 1.25, 0, 1) ** 1.4 * 235
    v = np.zeros((H, W, 4), np.uint8)
    v[..., 3] = a.astype(np.uint8)
    return Image.fromarray(v, "RGBA")


VIGNETTE = _vignette()
RNG = np.random.default_rng(7)
GRANOS = []
for _ in range(6):
    g = RNG.normal(0, 1, (H // 2, W // 2))
    n = np.zeros((H // 2, W // 2, 4), np.uint8)
    n[..., :3] = 255 if False else 128
    n[..., 0] = n[..., 1] = n[..., 2] = np.clip(128 + g * 60, 0, 255).astype(np.uint8)
    n[..., 3] = 16
    GRANOS.append(Image.fromarray(n, "RGBA").resize((W, H), Image.NEAREST))


@lru_cache(None)
def fondo_base(ruta, tono):
    """Fotograma del juego: desenfocado, oscurecido y teñido. Algo más grande que la pantalla para moverlo."""
    im = Image.open(ruta).convert("RGB")
    bw, bh = int(W * 1.18), int(H * 1.18)
    esc = max(bw / im.width, bh / im.height)
    im = im.resize((int(im.width * esc) + 2, int(im.height * esc) + 2), Image.LANCZOS)
    l, t = (im.width - bw) // 2, (im.height - bh) // 2
    im = im.crop((l, t, l + bw, t + bh)).filter(ImageFilter.GaussianBlur(26))
    arr = np.asarray(im).astype(np.float32) * 0.34
    tinte = np.array(COLORES.get(tono, ROSA), np.float32)
    arr = arr * 0.78 + tinte * 0.10
    # degradado oscuro arriba y abajo
    yy = np.linspace(0, 1, bh)[:, None, None]
    arr *= (0.55 + 0.45 * np.sin(np.pi * np.clip(yy, 0, 1)))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def fondo(ruta, tono, t, i_escena):
    base = fondo_base(ruta, tono)
    mx, my = base.width - W, base.height - H
    k = (t * 0.06 + i_escena * 0.37) % 2
    k = k if k <= 1 else 2 - k
    x = int(mx * (0.2 + 0.6 * k))
    y = int(my * (0.5 + 0.35 * math.sin(t * 0.35 + i_escena)))
    return base.crop((x, y, x + W, y + H)).convert("RGBA")


# ------------------------------------------------------------------ texto
def texto_capa(texto, f, color, stroke=0, glow=None, glow_r=18):
    """Imagen RGBA recortada con el texto (y su brillo)."""
    bbox = f.getbbox(texto, stroke_width=stroke)
    pad = glow_r * 3 if glow else 10
    w, h = bbox[2] - bbox[0] + pad * 2, bbox[3] - bbox[1] + pad * 2
    capa = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    pos = (pad - bbox[0], pad - bbox[1])
    if glow:
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(g).text(pos, texto, font=f, fill=(*glow, 255), stroke_width=stroke + 4)
        g = g.filter(ImageFilter.GaussianBlur(glow_r))
        capa.alpha_composite(g)
        capa.alpha_composite(g)
    d.text(pos, texto, font=f, fill=(*color, 255), stroke_width=stroke, stroke_fill=(10, 4, 24, 255))
    return capa


def pegar(dst, capa, cx, cy, escala=1.0, alfa=1.0):
    if alfa <= 0.01:
        return
    if abs(escala - 1) > 0.005:
        capa = capa.resize((max(1, int(capa.width * escala)), max(1, int(capa.height * escala))), Image.BILINEAR)
    if alfa < 0.999:
        capa = capa.copy()
        capa.putalpha(capa.getchannel("A").point(lambda v: int(v * alfa)))
    dst.alpha_composite(capa, (int(cx - capa.width / 2), int(cy - capa.height / 2)))


def ajustar(texto, ruta, tam, ancho):
    while tam > 30 and fuente(ruta, tam).getlength(texto) > ancho:
        tam -= 4
    return fuente(ruta, tam)


def num_fmt(v, dec=0):
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ escenas
def esc_numero(c, t, e):
    """Número gigante que cuenta y cae de golpe."""
    p = ease_out(t / e.get("cuenta", 0.9))
    v = e["desde"] + (e["hasta"] - e["desde"]) * p
    txt = e.get("prefijo", "") + num_fmt(v, e.get("dec", 0)) + e.get("sufijo", "")
    col = COLORES[e.get("color", "amarillo")]
    f = ajustar(txt, F_BLACK, e.get("tam", 420), W - 140)
    capa = texto_capa(txt, f, col, stroke=0, glow=col, glow_r=26)
    esc = 1.0 + 0.5 * (1 - ease_back(t / 0.45))
    pegar(c, capa, W / 2, e.get("y", 900), esc)
    if e.get("arriba"):
        cap = cache_texto(e["arriba"], F_XB, 58, BLANCO)
        pegar(c, cap, W / 2, e.get("y", 900) - f.size * 0.62 - 40, 1, ease_out((t - 0.1) / 0.3))
    if e.get("abajo"):
        lineas = e["abajo"].split("\n")
        for i, l in enumerate(lineas):
            cap = cache_texto(l, F_BLACK, e.get("tam_abajo", 76), BLANCO if i else COLORES[e.get("color_abajo", "blanco")])
            a = ease_out((t - 0.45 - i * 0.18) / 0.3)
            pegar(c, cap, W / 2, e.get("y", 900) + f.size * 0.55 + 70 + i * 96 + 30 * (1 - a), 1, a)


@lru_cache(None)
def cache_texto(txt, ruta, tam, color, glow=None):
    f = ajustar(txt, ruta, tam, W - 150)
    return texto_capa(txt, f, color, stroke=0, glow=glow)


def esc_titular(c, t, e):
    """Líneas que entran palabra a palabra. Palabras entre *asteriscos* van en color."""
    lineas = e["lineas"]
    tam = e.get("tam", 112)
    alto = tam * 1.12
    y0 = e.get("y", 880) - alto * (len(lineas) - 1) / 2
    k = 0
    col_acento = COLORES[e.get("color", "amarillo")]
    for i, linea in enumerate(lineas):
        palabras = linea.split()
        f = ajustar(linea.replace("*", ""), F_BLACK, tam, W - 130)
        anchos = [f.getlength(p.replace("*", "")) for p in palabras]
        esp = f.getlength(" ")
        total = sum(anchos) + esp * (len(palabras) - 1)
        x = (W - total) / 2
        for p, a in zip(palabras, anchos):
            acento = p.startswith("*")
            limpio = p.replace("*", "")
            tt = t - 0.09 * k
            if tt > 0:
                capa = cache_texto(limpio, F_BLACK, f.size, col_acento if acento else BLANCO,
                                   glow=col_acento if acento else None)
                esc = 0.6 + 0.4 * ease_back(tt / 0.3)
                pegar(c, capa, x + a / 2, y0 + i * alto + 20 * (1 - ease_out(tt / 0.25)), esc, ease_out(tt / 0.15))
            x += a + esp
            k += 1
    if e.get("sub"):
        a = ease_out((t - 0.09 * k - 0.15) / 0.35)
        cap = cache_texto(e["sub"], F_SEMI, 52, GRIS)
        pegar(c, cap, W / 2, y0 + len(lineas) * alto + 40, 1, a)


def esc_barras(c, t, e):
    d = ImageDraw.Draw(c)
    if e.get("titulo"):
        pegar(c, cache_texto(e["titulo"], F_BLACK, 74, BLANCO), W / 2, 470, 1, ease_out(t / 0.3))
    items = e["items"]
    vmin, vmax = e.get("min", 0), e.get("max", max(i[1] for i in items))
    x0, x1 = 90, W - 120
    y = 600
    paso = e.get("paso", 175)
    for k, (etq, val, dest) in enumerate(items):
        tt = t - 0.25 - k * 0.22
        if tt <= 0:
            y += paso
            continue
        a = ease_out(tt / 0.25)
        col = AMARILLO if dest else (255, 255, 255)
        f = fuente(F_XB, 46)
        d.text((x0, y), etq, font=f, fill=(*(col if dest else GRIS), int(255 * a)))
        frac = (val - vmin) / (vmax - vmin)
        largo = (x1 - x0 - 210) * frac * ease_out(tt / 0.7)
        yb = y + 62
        d.rounded_rectangle([x0, yb, x1 - 210, yb + 56], 14, fill=(255, 255, 255, int(28 * a)))
        if largo > 4:
            barra = Image.new("RGBA", (int(largo) + 60, 116), (0, 0, 0, 0))
            db = ImageDraw.Draw(barra)
            colb = ROSA if not dest else AMARILLO
            if dest:
                db.rounded_rectangle([30, 30, 30 + int(largo), 86], 14, fill=(*colb, 255))
                barra = barra.filter(ImageFilter.GaussianBlur(14))
                ImageDraw.Draw(barra).rounded_rectangle([30, 30, 30 + int(largo), 86], 14, fill=(*colb, 255))
            else:
                db.rounded_rectangle([30, 30, 30 + int(largo), 86], 14, fill=(*colb, 230))
            c.alpha_composite(barra, (x0 - 30, yb - 30))
        v = val * ease_out(tt / 0.7)
        txt = num_fmt(v, e.get("dec", 0)) + e.get("sufijo", "")
        fv = fuente(F_BLACK, 64)
        fv = ajustar(txt, F_BLACK, 64, 190)
        d.text((x1 - 190, yb - 8 + (64 - fv.size) / 2), txt, font=fv, fill=(*col, int(255 * a)))
        y += paso
    if e.get("nota"):
        a = ease_out((t - 0.4 - len(items) * 0.22) / 0.4)
        pegar(c, cache_texto(e["nota"], F_SEMI, 44, GRIS), W / 2, y + 30, 1, a)


def esc_versus(c, t, e):
    if e.get("titulo"):
        pegar(c, cache_texto(e["titulo"], F_BLACK, 80, BLANCO), W / 2, 520, 1, ease_out(t / 0.3))
    d = ImageDraw.Draw(c)
    for k, lado in enumerate(e["lados"]):
        cx = W * (0.27 if k == 0 else 0.73)
        tt = t - 0.2 - k * 0.45
        if tt <= 0:
            continue
        a = ease_out(tt / 0.3)
        col = COLORES[lado.get("color", "blanco")]
        # tarjeta
        caja = Image.new("RGBA", (440, 640), (0, 0, 0, 0))
        dc = ImageDraw.Draw(caja)
        dc.rounded_rectangle([0, 0, 439, 639], 36, fill=(12, 8, 30, int(200 * a)), outline=(*col, int(255 * a)), width=5)
        pegar(c, caja, cx, 960, 0.9 + 0.1 * ease_back(tt / 0.35), 1)
        fa = ajustar(lado["arriba"], F_XB, 50, 380)
        pegar(c, cache_texto(lado["arriba"], F_XB, fa.size, GRIS), cx, 730, 1, a)
        v = lado["num"] * ease_out(tt / 0.8)
        txt = num_fmt(v) + lado.get("sufijo", "")
        f = ajustar(txt, F_BLACK, 190, 380)
        pegar(c, texto_capa(txt, f, col, glow=col if lado.get("brillo") else None), cx, 940, 1, a)
        for i, l in enumerate(lado["abajo"].split("\n")):
            pegar(c, cache_texto(l, F_XB, 48, BLANCO), cx, 1120 + i * 62, 1, a)
    if e.get("nota"):
        a = ease_out((t - 1.3) / 0.4)
        pegar(c, cache_texto(e["nota"], F_BLACK, 66, AMARILLO, glow=AMARILLO), W / 2, 1380, 0.9 + 0.1 * ease_back((t - 1.3) / 0.4), a)
    d.line([(W / 2, 700), (W / 2, 1220)], fill=(255, 255, 255, 0))


def esc_linea(c, t, e):
    """Gráfica de línea que se dibuja sola (crecimiento)."""
    if e.get("titulo"):
        pegar(c, cache_texto(e["titulo"], F_BLACK, 72, BLANCO), W / 2, 470, 1, ease_out(t / 0.3))
    pts = e["puntos"]
    x0, x1, y0, y1 = 130, W - 230, 1260, 640
    vmax = e.get("max", max(p[1] for p in pts) * 1.1)
    xy = [(x0 + (x1 - x0) * i / (len(pts) - 1), y0 - (y0 - y1) * p[1] / vmax) for i, p in enumerate(pts)]
    d = ImageDraw.Draw(c)
    for g in range(5):
        yy = y0 - (y0 - y1) * g / 4
        d.line([(x0, yy), (x1, yy)], fill=(255, 255, 255, 30), width=2)
    prog = ease_out((t - 0.2) / 1.6) * (len(pts) - 1)
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(capa)
    camino = []
    for i in range(len(pts) - 1):
        f = clamp(prog - i)
        if f <= 0:
            break
        xa, ya = xy[i]
        xb, yb = xy[i + 1]
        camino += [(xa, ya), (xa + (xb - xa) * f, ya + (yb - ya) * f)]
    if len(camino) >= 2:
        # relleno bajo la curva
        poly = camino + [(camino[-1][0], y0), (camino[0][0], y0)]
        rel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(rel).polygon(poly, fill=(*ROSA, 60))
        c.alpha_composite(rel)
        dl.line(camino, fill=(*ROSA, 255), width=14, joint="curve")
        glow = capa.filter(ImageFilter.GaussianBlur(16))
        c.alpha_composite(glow)
        c.alpha_composite(capa)
    for i, (etq, val) in enumerate(pts):
        if prog + 0.001 < i:
            break
        x, y = xy[i]
        ultimo = i == len(pts) - 1
        r = 20 if ultimo else 13
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*(AMARILLO if ultimo else BLANCO), 255))
        fe = fuente(F_SEMI, 38)
        d.text((x - fe.getlength(etq) / 2, y0 + 24), etq, font=fe, fill=(*GRIS, 255))
        fv = fuente(F_BLACK, 74 if ultimo else 50)
        txt = num_fmt(val, e.get("dec", 1)) + e.get("sufijo", "")
        tx = min(max(x - fv.getlength(txt) / 2, 40), W - 60 - fv.getlength(txt))
        d.text((tx, y - (110 if ultimo else 80)), txt, font=fv, fill=(*(AMARILLO if ultimo else BLANCO), 255))


def esc_cta(c, t, e):
    pegar(c, cache_texto(e["texto"], F_BLACK, 120, BLANCO, glow=ROSA), W / 2, 850,
          0.6 + 0.4 * ease_back(t / 0.35), ease_out(t / 0.2))
    for i, l in enumerate(e.get("sub", "").split("\n")):
        if l:
            a = ease_out((t - 0.35 - 0.15 * i) / 0.3)
            pegar(c, cache_texto(l, F_XB, 60, AMARILLO), W / 2, 1010 + i * 80, 1, a)
    if e.get("pulso"):
        p = 0.5 + 0.5 * math.sin(t * 7)
        pegar(c, cache_texto(e["pulso"], F_BLACK, 70, BLANCO), W / 2, 1230, 1 + 0.05 * p, ease_out((t - 0.7) / 0.3))


ESCENAS = {"numero": esc_numero, "titular": esc_titular, "barras": esc_barras, "versus": esc_versus,
           "linea": esc_linea, "cta": esc_cta}


# ------------------------------------------------------------------ marco fijo
def marco(c, t, total, n_esc, i_esc, guion):
    d = ImageDraw.Draw(c)
    # segmentos de progreso tipo stories
    x0, x1, y = 90, W - 90, 210
    hueco = 10
    ancho = (x1 - x0 - hueco * (n_esc - 1)) / n_esc
    for k in range(n_esc):
        xa = x0 + k * (ancho + hueco)
        d.rounded_rectangle([xa, y, xa + ancho, y + 8], 4, fill=(255, 255, 255, 70))
        f = 1 if k < i_esc else (guion["_prog"] if k == i_esc else 0)
        if f > 0:
            d.rounded_rectangle([xa, y, xa + ancho * f, y + 8], 4, fill=(255, 255, 255, 240))
    # chip
    fc = fuente(F_BLACK, 40)
    chip = guion.get("chip", "GTA VI")
    wc = fc.getlength(chip)
    d.rounded_rectangle([90, 250, 90 + wc + 44, 250 + 66], 12, fill=(*ROSA, 255))
    d.text((112, 259), chip, font=fc, fill=(255, 255, 255, 255))
    fs = fuente(F_XB, 36)
    d.text((90 + wc + 66, 262), guion.get("chip2", ""), font=fs, fill=(255, 255, 255, 220))
    # marca
    fm = fuente(F_BLACK, 34)
    txt = "VICE CLIPS"
    d.text(((W - fm.getlength(txt)) / 2, 1600), txt, font=fm, fill=(255, 255, 255, 150))
    if guion.get("fuente"):
        ff = fuente(F_MED, 28)
        d.text(((W - ff.getlength(guion["fuente"])) / 2, 1650), guion["fuente"], font=ff, fill=(255, 255, 255, 110))


# ------------------------------------------------------------------ sonido
def sfx(total, cortes, golpes, ruta_musica, salida):
    sr = 44100
    n = int(total * sr)
    with wave.open(str(ruta_musica)) as w:
        m = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2)[:, 0].astype(np.float32) / 32767
    audio = np.zeros(n, np.float32)
    audio[: min(n, len(m))] += m[:n] * 0.55
    rng = np.random.default_rng(3)
    for tc in cortes:  # whoosh
        L = int(0.35 * sr)
        i = int(max(0, tc - 0.18) * sr)
        tt = np.arange(L) / sr
        ruido = rng.uniform(-1, 1, L)
        k = np.exp(-((tt - 0.18) / 0.08) ** 2)
        # filtro paso bajo simple que sube
        out = np.zeros(L)
        a = 0.0
        for j in range(L):
            alpha = 0.05 + 0.5 * k[j]
            a += alpha * (ruido[j] - a)
            out[j] = a
        seg = audio[i:i + L]
        seg += (out * k * 0.5)[: len(seg)]
    for tg in golpes:  # impacto
        L = int(0.6 * sr)
        i = int(tg * sr)
        tt = np.arange(L) / sr
        boom = np.sin(2 * np.pi * (45 + 120 * np.exp(-tt * 25)) * tt) * np.exp(-tt * 6)
        clic = rng.uniform(-1, 1, L) * np.exp(-tt * 60)
        seg = audio[i:i + L]
        seg += ((boom * 0.8 + clic * 0.25))[: len(seg)]
    audio = np.tanh(audio * 1.2) * 0.85
    est = np.stack([audio, audio], 1)
    with wave.open(str(salida), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((est * 32767).astype(np.int16).tobytes())


# ------------------------------------------------------------------ render
def fotograma(guion, t):
    escenas = guion["escenas"]
    total = sum(e["dur"] for e in escenas)
    acc, i = 0.0, 0
    while i < len(escenas) - 1 and t >= acc + escenas[i]["dur"]:
        acc += escenas[i]["dur"]
        i += 1
    e = escenas[i]
    lt = t - acc
    guion["_prog"] = clamp(lt / e["dur"])
    bgs = guion["fondos"]
    c = fondo(str(AQUI / "bg" / bgs[i % len(bgs)]), e.get("tono", "rosa"), t, i)
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ESCENAS[e["tipo"]](capa, lt, e)
    # golpe de zoom al entrar y salida rápida
    z = 1 + 0.07 * (1 - ease_out(lt / 0.3))
    if z > 1.002:
        cw, ch = int(W * z), int(H * z)
        capa = capa.resize((cw, ch), Image.BILINEAR).crop(((cw - W) // 2, (ch - H) // 2, (cw - W) // 2 + W, (ch - H) // 2 + H))
    sale = clamp((e["dur"] - lt) / 0.12)
    if sale < 1:
        capa.putalpha(capa.getchannel("A").point(lambda v: int(v * sale)))
    c.alpha_composite(capa)
    c.alpha_composite(VIGNETTE)
    marco(c, t, total, len(escenas), i, guion)
    c.alpha_composite(GRANOS[int(t * FPS) % len(GRANOS)])
    if lt < 0.1 and i > 0:  # destello del corte
        c.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(150 * (1 - lt / 0.1)))))
    return c.convert("RGB")


def render(guion, solo_frames=False):
    nombre = guion["id"]
    escenas = guion["escenas"]
    total = sum(e["dur"] for e in escenas)
    if solo_frames:
        acc = 0
        for k, e in enumerate(escenas):
            tt = acc + e["dur"] * 0.8
            fotograma(guion, tt).save(SALIDA / f"{nombre}-f{k}.jpg", quality=88)
            acc += e["dur"]
        return
    cortes, golpes, acc = [], [], 0.0
    for e in escenas:
        if acc > 0:
            cortes.append(acc)
        if e["tipo"] in ("numero",) or e.get("golpe"):
            golpes.append(acc + 0.05)
        acc += e["dur"]
    raise SystemExit("usar voz_render.py")
    mus = None
    wav = SALIDA / f"{nombre}.wav"
    sfx(total, cortes, golpes, mus, wav)
    tmp = SALIDA / f"{nombre}.tmp.mp4"
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(tmp)],
        stdin=subprocess.PIPE)
    for k in range(int(total * FPS)):
        proc.stdin.write(fotograma(guion, k / FPS).tobytes())
    proc.stdin.close()
    if proc.wait() == 0:
        tmp.rename(SALIDA / f"{nombre}.mp4")
    return SALIDA / f"{nombre}.mp4"


if __name__ == "__main__":
    guiones = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    solo = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    frames = "--frames" in sys.argv
    for g in guiones:
        if solo and g["id"] != solo:
            continue
        print("render", g["id"], render(g, frames), flush=True)
