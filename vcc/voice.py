"""Voz en off. Principal: ElevenLabs. Respaldo: edge-tts (gratis). Último recurso: silencio."""
import asyncio
import logging
import subprocess

import requests

log = logging.getLogger("vcc")


def duracion(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def _elevenlabs(texto, salida, cfg):
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['elevenlabs_voice_id']}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": cfg["elevenlabs_api_key"], "Content-Type": "application/json"},
        json={
            "text": texto,
            "model_id": cfg.get("elevenlabs_modelo", "eleven_multilingual_v2"),
            # algo de energía: menos estable = más expresivo
            "voice_settings": {"stability": 0.35, "similarity_boost": 0.8, "style": 0.45,
                               "use_speaker_boost": True},
        },
        timeout=60,
    )
    r.raise_for_status()
    with open(salida, "wb") as f:
        f.write(r.content)


def _edge(texto, salida, voz):
    import edge_tts

    async def _run():
        await edge_tts.Communicate(texto, voz, rate="+12%").save(str(salida))

    asyncio.run(_run())


def tts(texto: str, salida, cfg) -> float:
    """Genera la locución en `salida` (mp3) y devuelve su duración en segundos."""
    key = cfg.get("elevenlabs_api_key", "")
    if key and not key.startswith("PONER"):
        try:
            _elevenlabs(texto, salida, cfg)
            return duracion(salida)
        except Exception as e:
            log.warning("ElevenLabs falló (%s). Paso a la voz de respaldo.", e)
    try:
        _edge(texto, salida, cfg.get("voz_respaldo", "es-ES-AlvaroNeural"))
        return duracion(salida)
    except Exception as e:
        log.warning("Voz de respaldo no disponible (%s). Uso silencio.", e)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-t", "1.2", str(salida)], check=True)
        return 1.2
