"""Momentos Locos Gaming — genera Shorts con los mejores clips de Twitch.

Uso:
  python main.py short       -> busca clips de streamers autorizados y monta un Short "top 3"
  python main.py descubrir   -> lista streamers en español con audiencia en GTA (para pedir permiso)
"""
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from vcc.editor import montar_top
from vcc.twitch import Twitch

RAIZ = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vcc")

ENV = {
    "twitch_client_id": "TWITCH_CLIENT_ID",
    "twitch_client_secret": "TWITCH_CLIENT_SECRET",
    "elevenlabs_api_key": "ELEVENLABS_API_KEY",
    "elevenlabs_voice_id": "ELEVENLABS_VOICE_ID",
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


def metadatos(clips, cfg):
    top = clips[0]
    hoy = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%d/%m")
    titulo = f"Lo más LOCO de GTA 6 hoy 🤯 ({hoy}) #gta6 #shorts"
    creditos = "\n".join(f"#{i + 1} {c['streamer']} → https://twitch.tv/{c['streamer']}"
                         for i, c in enumerate(clips))
    descripcion = (
        f"Los momentos más locos de GTA VI de hoy en los directos de Twitch.\n\n"
        f"🎮 Créditos (¡ve a verlos en directo!):\n{creditos}\n\n"
        f"Clips usados con permiso de sus creadores. Si eres uno de ellos y quieres que retiremos tu clip, escríbenos.\n"
        f"{cfg.get('mencion_voz', '')}\n\n"
        f"#GTA6 #GTAVI #GrandTheftAuto #Shorts #Twitch #Gaming"
    ).strip()
    etiquetas = ["GTA 6", "GTA VI", "Grand Theft Auto VI", "GTA 6 momentos", "GTA 6 clips",
                 "GTA 6 español", "Twitch"] + [c["streamer"] for c in clips]
    return {"titulo": titulo[:100], "descripcion": descripcion, "etiquetas": etiquetas,
            "clips": [{"streamer": c["streamer"], "url": c["url"], "titulo": c["titulo"],
                       "vistas": c["vistas"]} for c in clips]}


def cmd_short(cfg):
    autorizados = [s for s in cfg["streamers_autorizados"] if s.strip()]
    if not autorizados:
        log.warning("No hay streamers autorizados en config.json. No se genera nada.")
        return None
    tw = Twitch(cfg["twitch_client_id"], cfg["twitch_client_secret"])
    game_id = tw.game_id(cfg["juego"])
    ids = tw.user_ids(autorizados)
    usados = cargar_usados()

    candidatos = []
    for login, uid in ids.items():
        for c in tw.clips_de_streamer(uid, game_id, cfg["horas_atras"]):
            if c["id"] in usados or c["view_count"] < cfg["vistas_minimas"]:
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
        if len(elegidos) == cfg["clips_por_short"]:
            break
    if len(elegidos) < cfg["clips_por_short"]:
        log.info("Solo hay %d clips nuevos; hacen falta %d. Se espera a la siguiente ronda.",
                 len(elegidos), cfg["clips_por_short"])
        return None

    trabajo = RAIZ / cfg["carpeta_trabajo"]
    trabajo.mkdir(exist_ok=True)
    for c in elegidos:
        c["ruta"] = descargar(c["url"], trabajo / f"{c['id']}.mp4")

    salida_dir = RAIZ / cfg["carpeta_bandeja"]
    salida_dir.mkdir(exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    video = salida_dir / f"short-{marca}.mp4"
    montar_top(elegidos, video, cfg, trabajo)

    meta = metadatos(elegidos, cfg)
    meta["video"] = video.name
    (salida_dir / f"short-{marca}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    guardar_usados(usados | {c["id"] for c in elegidos})
    log.info("Short listo: %s", video)
    return video


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
    else:
        cmd_short(cfg)
