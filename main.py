"""Momentos Locos Gaming — genera Shorts con los mejores clips de Twitch.

Uso:
  python main.py short       -> busca los clips más vistos en español y monta un Short por clip
  python main.py directo     -> graba el directo de $CANAL durante $MINUTOS y corta los picos del chat
  python main.py descubrir   -> lista streamers en español con audiencia en GTA (los más vistos)
"""
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from vcc.editor import montar_unico
from vcc.twitch import Twitch

RAIZ = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vcc")

ENV = {
    "twitch_client_id": "TWITCH_CLIENT_ID",
    "twitch_client_secret": "TWITCH_CLIENT_SECRET",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
    "juego": "JUEGO",  # para pruebas con otro juego (p. ej. GTA V)
}


def cargar_config():
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    for clave, var in ENV.items():
        if os.environ.get(var):
            cfg[clave] = os.environ[var]
    return cfg


def cargar_usados():
    p = RAIZ / "data" / "usados.json"
    return set(json.loads(p.read_text())) if p.exists() else set()


def guardar_usados(usados):
    p = RAIZ / "data" / "usados.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(sorted(usados), indent=0))


def descargar(url, destino):
    subprocess.run(["yt-dlp", "-q", "-f", "best[ext=mp4]/best", "-o", str(destino), url], check=True)
    return destino


def metadatos(c, cfg):
    titulo_clip = (c["titulo"] or "").strip()
    titulo = f"{titulo_clip} | {c['streamer']} #gta6 #shorts" if titulo_clip else f"{c['streamer']} en GTA #gta6 #shorts"
    descripcion = (
        f"🎮 Clip de {c['streamer']} en directo → https://twitch.tv/{c['login']}\n\n"
        f"#GTA6 #GTAVI #GrandTheftAuto #Shorts #Twitch #Gaming"
    )
    etiquetas = ["GTA 6", "GTA VI", "Grand Theft Auto VI", "GTA 6 clips", "GTA 6 español", "Twitch", c["streamer"]]
    return {"titulo": titulo[:100], "descripcion": descripcion, "etiquetas": etiquetas,
            "clip": {"streamer": c["streamer"], "url": c["url"], "titulo": c["titulo"], "vistas": c["vistas"]}}


def cmd_short(cfg):
    tw = Twitch(cfg["twitch_client_id"], cfg["twitch_client_secret"])
    game_id = tw.game_id(cfg["juego"])
    usados = cargar_usados()
    excluidos = {s.strip().lower() for s in cfg.get("streamers_excluidos", []) if s.strip()}

    # Clips más vistos del juego en español (los crean los propios espectadores)
    brutos = tw.clips_del_juego(game_id, cfg["horas_atras"], cfg["idioma"])
    # y además, los clips de los streamers en español que están jugando ahora
    for uid, _login in tw.directos(game_id, cfg["idioma"]):
        brutos += tw.clips_de_streamer(uid, game_id, cfg["horas_atras"])
    vistos_ids = set()
    brutos = [c for c in brutos if not (c["id"] in vistos_ids or vistos_ids.add(c["id"]))]
    candidatos = []
    for c in brutos:
        login = c["broadcaster_name"].lower()
        if c["id"] in usados or login in excluidos or c["view_count"] < cfg["vistas_minimas"]:
            continue
        candidatos.append({"id": c["id"], "url": c["url"], "streamer": c["broadcaster_name"],
                           "login": login, "titulo": c["title"], "vistas": c["view_count"],
                           "duracion": c.get("duration", 30)})
    # máximo 1 clip por streamer para variar, ordenados por vistas
    candidatos.sort(key=lambda c: c["vistas"], reverse=True)
    elegidos, vistos = [], set()
    for c in candidatos:
        if c["login"] in vistos:
            continue
        elegidos.append(c)
        vistos.add(c["login"])
        if len(elegidos) == cfg["shorts_por_ronda"]:
            break
    if not elegidos:
        log.info("No hay clips nuevos con suficientes visitas. Se espera a la siguiente ronda.")
        return None

    trabajo = RAIZ / cfg["carpeta_trabajo"]
    trabajo.mkdir(exist_ok=True)
    salida_dir = RAIZ / cfg["carpeta_bandeja"]
    salida_dir.mkdir(exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    for n, c in enumerate(elegidos, 1):
        ruta = descargar(c["url"], trabajo / f"{c['id']}.mp4")
        video = salida_dir / f"short-{marca}-{n}.mp4"
        montar_unico(ruta, video, c["streamer"], cfg, trabajo)
        meta = metadatos(c, cfg)
        meta["video"] = video.name
        (salida_dir / f"short-{marca}-{n}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        log.info("Short listo: %s (%s, %d visitas)", video.name, c["streamer"], c["vistas"])

    guardar_usados(usados | {c["id"] for c in elegidos})
    return elegidos


def cmd_directo(cfg, canal, minutos, cuantos=4):
    """Graba el directo de 'canal' durante 'minutos', lee el chat y monta un Short por cada pico."""
    from vcc import directo
    trabajo = RAIZ / cfg["carpeta_trabajo"]
    salida_dir = RAIZ / cfg["carpeta_bandeja"]
    salida_dir.mkdir(exist_ok=True)
    canal = canal.strip().lower().lstrip("@")
    video, t0, mensajes = directo.grabar(canal, minutos, trabajo / f"directo-{canal}.ts")
    dur = float(subprocess.run(["ffprobe", "-v", "0", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(video)], capture_output=True, text=True).stdout.strip() or 0)
    log.info("Grabados %.0f s y %d mensajes de chat", dur, len(mensajes))
    picos = directo.momentos(t0, mensajes, dur, cuantos)
    if not picos:
        log.info("El chat no ha tenido picos claros en esta grabación.")
        return []
    marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    hechos = []
    for n, (ini, fin, fuerza, muestra) in enumerate(picos, 1):
        corte = directo.cortar(video, ini, fin, trabajo / f"corte-{canal}-{n}.mp4")
        nombre = f"directo-{canal}-{marca}-{n}"
        montar_unico(corte, salida_dir / f"{nombre}.mp4", canal, cfg, trabajo)
        meta = {
            "titulo": f"{canal} en GTA 6 #gta6 #shorts",
            "descripcion": f"🎮 Momento del directo de {canal} → https://twitch.tv/{canal}\n\n"
                           f"#GTA6 #GTAVI #GrandTheftAuto #Shorts #Twitch #Gaming",
            "etiquetas": ["GTA 6", "GTA VI", "Grand Theft Auto VI", "GTA 6 clips", "GTA 6 español", "Twitch", canal],
            "directo": {"canal": canal, "segundo_inicio": round(ini), "fuerza_chat": fuerza, "chat": muestra},
            "video": f"{nombre}.mp4",
        }
        (salida_dir / f"{nombre}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        log.info("Short listo: %s (chat x%.1f)", nombre, fuerza)
        hechos.append(nombre)
    return hechos


def cmd_descubrir(cfg):
    """Streamers en español jugando ahora a GTA (VI o V), ordenados por espectadores."""
    tw = Twitch(cfg["twitch_client_id"], cfg["twitch_client_secret"])
    filas = []
    for juego in [cfg["juego"], "Grand Theft Auto V"]:
        try:
            gid = tw.game_id(juego)
        except RuntimeError:
            continue
        res = tw._get("streams", {"game_id": gid, "language": "es", "first": 100})["data"]
        for s in res:
            filas.append((s["viewer_count"], s["user_login"], s["user_name"], juego, s["title"][:70]))
    filas.sort(reverse=True)
    lineas = ["| Espectadores | Canal | Juego | Título del directo |", "| --- | --- | --- | --- |"]
    lineas += [f"| {v} | [{n}](https://twitch.tv/{l}) | {j} | {t.replace('|', '/')} |"
               for v, l, n, j, t in filas]
    (RAIZ / "data").mkdir(exist_ok=True)
    (RAIZ / "data" / "candidatos.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    cfg = cargar_config()
    orden = sys.argv[1] if len(sys.argv) > 1 else "short"
    if orden == "descubrir":
        cmd_descubrir(cfg)
    elif orden == "directo":
        cmd_directo(cfg, os.environ.get("CANAL") or "rubius", int(os.environ.get("MINUTOS") or 40))
    else:
        cmd_short(cfg)
