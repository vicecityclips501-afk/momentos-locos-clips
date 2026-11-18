"""Subtítulos: transcripción con faster-whisper y estilo 'karaoke' en ASS."""
import logging

log = logging.getLogger("vcc")

_model = None

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Inter Display Black,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,660,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

AMARILLO = r"{\c&H00D7FF&}"   # BGR: amarillo/dorado
BLANCO = r"{\c&HFFFFFF&}"


def _traducir(texto, destino="es"):
    """Traduce una frase al español (Google y, si falla, MyMemory). Si todo falla, devuelve None."""
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator
    except Exception as e:
        log.warning("Traducción no disponible: falta deep_translator (%s)", e)
        return None
    for nombre, fn in (("google", lambda: GoogleTranslator(source="auto", target=destino).translate(texto)),
                       ("mymemory", lambda: MyMemoryTranslator(source="en-US", target="es-ES").translate(texto))):
        try:
            r = fn()
            if r and r.strip() and r.strip().lower() != texto.strip().lower():
                return r
        except Exception as e:
            log.warning("Traducción %s falló (%s)", nombre, e)
    return None


def transcribir(audio_path, modelo="small", idioma="es"):
    """Devuelve una lista de palabras [(inicio, fin, texto)]. Lista vacía si falla.
    Con idioma="auto" detecta el idioma y, si no es español, traduce cada frase al español."""
    global _model
    try:
        from faster_whisper import WhisperModel
        if _model is None:
            _model = WhisperModel(modelo, device="cpu", compute_type="int8")
        segs, info = _model.transcribe(str(audio_path), language=None if idioma == "auto" else idioma,
                                       word_timestamps=True, vad_filter=True)
        segs = list(segs)
        palabras = []
        if idioma == "auto" and info.language != "es":
            log.info("Idioma detectado: %s → subtítulos traducidos al español", info.language)
            fallos = 0
            for s in segs:
                trad = _traducir(s.text.strip())
                if trad is None:
                    fallos += 1
                    trad = s.text.strip()
                ws = trad.split()
                if not ws:
                    continue
                paso = max(0.12, (s.end - s.start) / len(ws))
                for k, w in enumerate(ws):
                    palabras.append((s.start + k * paso, min(s.end, s.start + (k + 1) * paso), w))
            if segs and fallos > len(segs) / 2:
                raise RuntimeError(f"traducción fallida en {fallos}/{len(segs)} frases")
            return palabras
        for s in segs:
            for w in (s.words or []):
                t = w.word.strip()
                if t:
                    palabras.append((w.start, w.end, t))
        return palabras
    except Exception as e:
        log.warning("Transcripción no disponible (%s). Vídeo sin subtítulos.", e)
        return []


def _ts(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _limpia(txt):
    return txt.replace("{", "").replace("}", "").replace("\\", "").upper()


def escribir_ass(palabras, salida, por_bloque=3, margen_v=None):
    """Bloques de 3 palabras en mayúsculas; la palabra que suena, en amarillo."""
    cab = ASS_HEADER if margen_v is None else ASS_HEADER.replace(",660,1\n", f",{margen_v},1\n")
    lineas = [cab]
    for i in range(0, len(palabras), por_bloque):
        bloque = palabras[i:i + por_bloque]
        fin_bloque = bloque[-1][1]
        for j, (ini, fin, _) in enumerate(bloque):
            fin_evt = bloque[j + 1][0] if j + 1 < len(bloque) else fin_bloque
            texto = " ".join(
                (AMARILLO if k == j else BLANCO) + _limpia(w[2]) for k, w in enumerate(bloque)
            )
            # pequeño "pop" de escala al entrar cada bloque
            pop = r"{\fscx108\fscy108\t(0,90,\fscx100\fscy100)}" if j == 0 else ""
            lineas.append(f"Dialogue: 0,{_ts(ini)},{_ts(max(fin_evt, ini + 0.08))},Sub,,0,0,0,,{pop}{texto}")
    with open(salida, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
