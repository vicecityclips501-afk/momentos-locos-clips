"""Graba un directo de Twitch, lee su chat a la vez y corta los momentos en los que el chat explota.

El chat va casi en tiempo real respecto al streamer y el vídeo que grabamos lleva el mismo retraso
desde el principio, así que el retraso del directo se cancela: un mensaje que llega X segundos
después de empezar a grabar reacciona a lo que se ve en el segundo X - (tiempo de reacción) del vídeo.
"""
import logging
import re
import socket
import statistics
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("vcc.directo")

# Mensajes que indican que acaba de pasar algo (risas, sorpresa, gente pidiendo clip)
REACCION = re.compile(
    r"(?:j[aseiAJ]){2,}|jsj|xd+\b|kek|lul|omegalul|pog|lmao|\bclip|😂|🤣|💀|wtf|\bno{3,}\b|madre m[ií]a|dios m[ií]o|ostia|hostia",
    re.IGNORECASE,
)
REACCION_SEG = 4        # lo que tarda el chat en reaccionar a lo que ve
ANTES, DESPUES = 22, 6  # segundos de clip antes y después del pico de reacción
VENTANA = 8             # segundos sobre los que se mide la actividad del chat
SEPARACION = 75         # distancia mínima entre dos momentos elegidos


def _leer_chat(canal, fin, mensajes):
    """Lee el chat de forma anónima (como cualquier espectador sin cuenta) hasta 'fin'."""
    while time.time() < fin:
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=10)
            s.settimeout(5)
            s.sendall(f"NICK justinfan{int(time.time()) % 90000 + 10000}\r\nJOIN #{canal}\r\n".encode())
            buf = ""
            while time.time() < fin:
                try:
                    data = s.recv(8192).decode("utf-8", "ignore")
                except socket.timeout:
                    continue
                if not data:
                    break
                buf += data
                *lineas, buf = buf.split("\r\n")
                for linea in lineas:
                    if linea.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                        continue
                    m = re.search(r"PRIVMSG #\S+ :(.*)", linea)
                    if m:
                        mensajes.append((time.time(), m.group(1)))
            s.close()
        except OSError as e:
            log.warning("Chat desconectado (%s), reconectando…", e)
            time.sleep(3)


def grabar(canal, minutos, destino: Path):
    """Graba el directo y el chat. Devuelve (ruta_video, inicio_de_grabacion, mensajes)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    mensajes = []
    dur = f"{minutos // 60:02d}:{minutos % 60:02d}:00"
    proc = subprocess.Popen([
        "streamlink", "--twitch-disable-ads", "--hls-live-edge", "2", "--hls-duration", dur,
        "--loglevel", "warning", "-f", "-o", str(destino), f"https://twitch.tv/{canal}", "720p60,720p,best",
    ])
    # el chat empieza ya; el inicio real de la grabación es cuando aparecen los primeros bytes
    fin_chat = time.time() + minutos * 60 + 120
    hilo = threading.Thread(target=_leer_chat, args=(canal, fin_chat, mensajes), daemon=True)
    hilo.start()
    t0 = None
    while proc.poll() is None and t0 is None:
        if destino.exists() and destino.stat().st_size > 0:
            t0 = time.time()
        time.sleep(0.25)
    if t0 is None:
        raise RuntimeError(f"No se pudo grabar el directo de {canal} (¿está en directo?)")
    log.info("Grabando %s durante %d min…", canal, minutos)
    proc.wait()
    return destino, t0, mensajes


def momentos(t0, mensajes, duracion_video, cuantos=4):
    """Busca los picos del chat. Devuelve [(inicio, fin, puntuacion, muestra_de_mensajes)]."""
    n = int(duracion_video) + 1
    puntos = [0.0] * n
    textos = [[] for _ in range(n)]
    reac = [0] * n
    for t, txt in mensajes:
        seg = int(t - t0 - REACCION_SEG)
        if 0 <= seg < n:
            # las risas y reacciones pesan mucho más que el resto (así las votaciones del chat no cuentan)
            r = min(2, len(REACCION.findall(txt)))
            puntos[seg] += 0.3 + 3 * r
            reac[seg] += 1 if r else 0
            textos[seg].append(txt)
    suma = [sum(puntos[i:i + VENTANA]) for i in range(n)]
    if not any(suma):
        return []
    base = statistics.median(s for s in suma if s > 0) if any(s > 0 for s in suma) else 1
    candidatos = sorted(range(n), key=lambda i: suma[i], reverse=True)
    elegidos = []
    for i in candidatos:
        if suma[i] < base * 4 or len(elegidos) >= cuantos:
            break
        total = sum(len(textos[j]) for j in range(i, min(n, i + VENTANA)))
        if total and sum(reac[i:i + VENTANA]) / total < 0.25:
            continue  # pico de mensajes sin risas: votaciones, spam de códigos…
        pico = i + VENTANA / 2
        ini, fin = pico - ANTES, pico + DESPUES
        if ini < 0 or fin > duracion_video:
            continue
        if any(abs(pico - p) < SEPARACION for p, *_ in elegidos):
            continue
        muestra = [m for j in range(i, min(n, i + VENTANA)) for m in textos[j]][:15]
        elegidos.append((pico, ini, fin, round(suma[i] / base, 1), muestra))
    elegidos.sort()
    return [(ini, fin, fuerza, muestra) for _p, ini, fin, fuerza, muestra in elegidos]


def cortar(video, ini, fin, salida):
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-ss", f"{ini:.2f}", "-i", str(video), "-t", f"{fin - ini:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(salida),
    ], check=True)
    return salida
