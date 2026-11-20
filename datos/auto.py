"""Shorts de datos con voz gratis (edge-tts). Uso: python datos/auto.py <id> [<id> ...]
Lee datos/auto.json: cada guion lleva, por escena, el texto que dice la voz ("voz").
La duración de cada escena se ajusta a lo que tarda la voz."""
import asyncio, datetime, json, subprocess, sys, urllib.request, wave, os
from pathlib import Path

os.chdir(Path(__file__).parent)
sys.path.insert(0, '.')
import numpy as np
import edge_tts
import render2 as r

VOZ, VELOCIDAD = "es-ES-AlvaroNeural", "+10%"
PRE, POST, POST_FIN = 0.15, 0.3, 0.7
SR = 44100
REL = "https://github.com/vicecityclips501-afk/momentos-locos-clips/releases/download/"
FONDOS = [("directo-rubius-20261118-2015-2", 3), ("directo-rubius-20261118-2015-2", 12), ("short-20261118-1911-1", 3),
          ("short-20261118-1911-1", 12), ("directo-djmariio-20261118-1953-3", 3), ("directo-djmariio-20261118-1953-3", 12),
          ("directo-kaicenat-20261118-2003-3", 3), ("directo-kaicenat-20261118-2003-3", 12)]


def fondos():
    Path("bg").mkdir(exist_ok=True)
    for k, (tag, ss) in enumerate(FONDOS, 1):
        dst = Path(f"bg/bg{k}.png")
        if dst.exists():
            continue
        src = Path(f"bg/{tag}.mp4")
        if not src.exists():
            urllib.request.urlretrieve(REL + f"{tag}/{tag}.mp4", src)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-i", str(src), "-frames:v", "1",
                        "-vf", "crop=1080:608:0:656", str(dst)], check=True)


def decir(texto, destino):
    mp3 = destino.with_suffix(".mp3")
    for intento in range(3):
        try:
            asyncio.run(edge_tts.Communicate(texto, VOZ, rate=VELOCIDAD).save(str(mp3)))
            break
        except Exception:
            if intento == 2:
                raise
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-ac", "1", "-ar", str(SR), str(destino)], check=True)
    with wave.open(str(destino)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32767


def hacer(g):
    trozos = []
    for k, e in enumerate(g["escenas"]):
        a = decir(e["voz"], r.SALIDA / f"{g['id']}-l{k}.wav")
        trozos.append(a)
        fin = POST_FIN if k == len(g["escenas"]) - 1 else POST
        e["dur"] = round(PRE + len(a) / SR + fin, 3)
    total = sum(e["dur"] for e in g["escenas"])
    cortes, golpes, starts, acc = [], [], [], 0.0
    for e in g["escenas"]:
        starts.append(acc)
        if acc > 0:
            cortes.append(acc)
        if e["tipo"] == "numero" or e.get("golpe"):
            golpes.append(acc + 0.05)
        acc += e["dur"]
    sil = r.SALIDA / "sil.wav"
    with wave.open(str(sil), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(b"\0" * int(SR * (total + 1)) * 4)
    fx = r.SALIDA / f"{g['id']}-fx.wav"
    r.sfx(total, cortes, golpes, sil, fx)
    with wave.open(str(fx)) as w:
        mez = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2)[:, 0].astype(np.float32) / 32767
    mez = mez * 0.45
    for k, seg in enumerate(trozos):
        i = int((starts[k] + PRE) * SR)
        n = min(len(seg), len(mez) - i)
        mez[i:i + n] += seg[:n]
    mez = mez / (np.max(np.abs(mez)) + 1e-9) * 0.95
    mix = r.SALIDA / f"{g['id']}-mix.wav"
    with wave.open(str(mix), "w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.stack([mez, mez], 1) * 32767).astype(np.int16).tobytes())
    tmp = r.SALIDA / f"{g['id']}-auto.tmp.mp4"
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{r.W}x{r.H}",
                          "-r", str(r.FPS), "-i", "-", "-i", str(mix), "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                          "-shortest", "-movflags", "+faststart", str(tmp)], stdin=subprocess.PIPE)
    for f in range(int(total * r.FPS)):
        p.stdin.write(r.fotograma(g, f / r.FPS).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg falló en {g['id']}")
    dest = Path("../bandeja"); dest.mkdir(exist_ok=True)
    nombre = f"datos-{g['id']}-" + datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")
    tmp.rename(dest / f"{nombre}.mp4")
    (dest / f"{nombre}.json").write_text(json.dumps({"titulo": g.get("titulo", g["id"]), "tipo": "datos"}, ensure_ascii=False))
    print(g["id"], round(total, 1), flush=True)


if __name__ == "__main__":
    fondos()
    ids = sys.argv[1:]
    for g in json.load(open("auto.json")):
        if not ids or g["id"] in ids:
            hacer(g)
