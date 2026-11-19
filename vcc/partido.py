"""Formato de pantalla partida: cámara del streamer arriba, juego abajo.
Detecta la cámara (facecam) buscando una cara que no se mueve de sitio en varios fotogramas."""
import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

W = 1080
CAM_Y, CAM_H = 330, 620          # panel de la cámara
JUEGO_Y, JUEGO_H = 965, 720      # panel del juego
SUBS_MARGEN = 1920 - JUEGO_Y - 40  # subtítulos justo en la unión de los dos paneles


def _cv2():
    import cv2
    ruta = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not ruta.exists():
        return None, None
    return cv2, cv2.CascadeClassifier(str(ruta))


def detectar_camara(video, muestras=14):
    """Devuelve (x, y, w, h) del recorte de la cámara en píxeles del vídeo original, o None."""
    cv2, casc = _cv2()
    if casc is None:
        log.warning("Sin detector de caras: se usa el formato sin cámara")
        return None
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    vw, vh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    caras, leidos = [], 0
    for k in range(muestras):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / muestras))
        ok, im = cap.read()
        if not ok:
            continue
        leidos += 1
        esc = 1280 / vw * 2
        g = cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), None, fx=esc, fy=esc)
        for (x, y, w, h) in casc.detectMultiScale(g, 1.1, 7, minSize=(50, 50)):
            caras.append((k, x / esc, y / esc, w / esc))
    cap.release()
    if not leidos or not caras:
        return None
    # agrupar caras que están siempre en el mismo sitio (la facecam no se mueve)
    grupos = []
    for k, x, y, w in caras:
        cx, cy = x + w / 2, y + w / 2
        for gr in grupos:
            if abs(gr["cx"] - cx) < w * 0.6 and abs(gr["cy"] - cy) < w * 0.6:
                gr["frames"].add(k)
                gr["ws"].append(w)
                break
        else:
            grupos.append({"cx": cx, "cy": cy, "frames": {k}, "ws": [w]})
    mejor = max(grupos, key=lambda g: len(g["frames"]))
    if len(mejor["frames"]) < max(4, leidos * 0.45):
        log.info("No hay una cámara fija clara (%d/%d fotogramas)", len(mejor["frames"]), leidos)
        return None
    fw = sorted(mejor["ws"])[len(mejor["ws"]) // 2]
    if fw > vw * 0.22:          # cara enorme = el streamer a pantalla completa, no una facecam
        return None
    cw = fw * 4.0
    ch = cw * CAM_H / W
    x = mejor["cx"] - cw / 2
    y = mejor["cy"] - ch * 0.42
    x = max(0, min(vw - cw, x))
    y = max(0, min(vh - ch, y))
    caja = (int(x) // 2 * 2, int(y) // 2 * 2, int(cw) // 2 * 2, int(ch) // 2 * 2)
    log.info("Cámara detectada en %s (cara de %d px, %d/%d fotogramas)", caja, fw, len(mejor["frames"]), leidos)
    return caja


def filtro_partido(caja, ancho_video, alto_video, credito, fuente, fps=30):
    """Filtro de ffmpeg (entrada [0:v]) que monta fondo + cámara arriba + juego abajo. Sale en [vp].
    El juego se recorta hacia el lado contrario a la cámara para que no salga repetida."""
    x, y, w, h = caja
    alto_j = 820
    ancho_j = int(ancho_video * alto_j / alto_video) // 2 * 2
    sobra = max(0, ancho_j - W)
    off = sobra if x + w / 2 < ancho_video / 2 else 0
    return (
        f"[0:v]fps={fps},split=3[a][b][c];"
        f"[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:4,eq=brightness=-0.32[bg];"
        f"[b]crop={w}:{h}:{x}:{y},scale={W}:{CAM_H}:flags=lanczos,unsharp=5:5:0.8[cam];"
        f"[c]scale={ancho_j}:{alto_j},crop={W}:{JUEGO_H}:{off}:{(alto_j - JUEGO_H) // 2}[juego];"
        f"[bg][cam]overlay=0:{CAM_Y}[p1];"
        f"[p1][juego]overlay=0:{JUEGO_Y}[p2];"
        f"[p2]drawtext=fontfile='{fuente}':text='{credito}':fontsize=38:fontcolor=white:"
        f"x=34:y={CAM_Y}+22:box=1:boxcolor=0x9146FF:boxborderw=12[vp]"
    )


def prueba(video, salida):
    """Para probar a mano: python -m vcc.partido entrada.mp4 salida.mp4"""
    from vcc.editor import F_TEXTO
    import cv2
    caja = detectar_camara(video)
    if not caja:
        print("sin cámara")
        return
    cap = cv2.VideoCapture(str(video)); vw, vh = int(cap.get(3)), int(cap.get(4)); cap.release()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-filter_complex",
                    filtro_partido(caja, vw, vh, "twitch.tv/prueba", F_TEXTO), "-map", "[vp]", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", str(salida)], check=True)
    print("ok", caja)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    prueba(sys.argv[1], sys.argv[2])
