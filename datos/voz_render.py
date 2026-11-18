import json, subprocess, sys, wave, urllib.request, os
from pathlib import Path
os.chdir(Path(__file__).parent)
import numpy as np
sys.path.insert(0, '.')
import render2 as r
from PIL import Image

LINEAS = [(0,4.127347),(4.127347,6.19102),(10.318367,8.437551),(18.755918,7.88898),(26.644898,4.205714),(30.850612,3.004082),
          (33.854694,5.32898),(39.183673,6.269388),(45.453061,5.799184),(51.252245,8.829388),(60.081633,5.955918),(66.037551,3.474286),
          (69.511837,6.765714),(76.277551,5.799184),(82.076735,4.362449),(86.439184,6.269388),(92.708571,4.989388),(97.697959,2.586122)]
PRE, POST = 0.15, 0.3
for _k,_v in {0: (100.284082, 3.787755), 2: (104.071837, 8.280816), 3: (112.352653, 7.967347), 9: (120.32, 8.75102), 12: (129.071021, 7.235918), 15: (136.306939, 6.19102)}.items(): LINEAS[_k]=_v
REL = "https://github.com/vicecityclips501-afk/momentos-locos-clips/releases/download/"
FONDOS = [("directo-rubius-20261118-2015-2", 3), ("directo-rubius-20261118-2015-2", 12), ("short-20261118-1911-1", 3),
          ("short-20261118-1911-1", 12), ("directo-djmariio-20261118-1953-3", 3), ("directo-djmariio-20261118-1953-3", 12),
          ("directo-kaicenat-20261118-2003-3", 3), ("directo-kaicenat-20261118-2003-3", 12)]
Path("bg").mkdir(exist_ok=True)
for k, (tag, ss) in enumerate(FONDOS, 1):
    dst = Path(f"bg/bg{k}.png")
    if not dst.exists():
        src = Path(f"bg/{tag}.mp4")
        if not src.exists():
            urllib.request.urlretrieve(REL + f"{tag}/{tag}.mp4", src)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-i", str(src), "-frames:v", "1", "-vf", "crop=1080:608:0:656", str(dst)], check=True)
VOCES = ["https://assets.vidiq.com/voiceovers/fceff493-d94e-4abd-bb44-89712ca84f4d/5d8c25a5-bf4c-43e7-b8f2-ff28341af3ea.mp3",
         "https://assets.vidiq.com/voiceovers/fceff493-d94e-4abd-bb44-89712ca84f4d/77f07418-dc62-4378-8122-270094b84c67.mp3"]
for i, u in enumerate(VOCES):
    if not Path(f"v{i}.mp3").exists():
        urllib.request.urlretrieve(u, f"v{i}.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"v{i}.mp3", "-ac", "1", "-ar", "44100", f"v{i}.wav"], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "v0.wav", "-i", "v1.wav", "-filter_complex", "[0][1]concat=n=2:v=0:a=1", "voz.wav"], check=True)
with wave.open('voz.wav') as w:
    voz = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32767
sr = 44100
gs = json.load(open('guiones.json'))
solo = sys.argv[1] if len(sys.argv) > 1 else None
for gi, g in enumerate(gs):
    if solo and g['id'] != solo:
        continue
    lin = LINEAS[gi*6:(gi+1)*6]
    for k, e in enumerate(g['escenas']):
        e['dur'] = round(PRE + lin[k][1] + (POST if k < 5 else 0.7), 3)
    total = sum(e['dur'] for e in g['escenas'])
    # sfx sin música
    cortes, golpes, acc, starts = [], [], 0.0, []
    for e in g['escenas']:
        starts.append(acc)
        if acc > 0: cortes.append(acc)
        if e['tipo'] == 'numero' or e.get('golpe'): golpes.append(acc + 0.05)
        acc += e['dur']
    sil = r.SALIDA / 'sil.wav'
    with wave.open(str(sil), 'w') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(b'\0' * int(sr * (total + 1)) * 4)
    fx = r.SALIDA / f"{g['id']}-fx.wav"
    r.sfx(total, cortes, golpes, sil, fx)
    with wave.open(str(fx)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2)[:, 0].astype(np.float32) / 32767
    a = a * 0.45
    for k, (s0, d) in enumerate(lin):
        seg = voz[int(s0*sr):int((s0+d)*sr)]
        i = int((starts[k] + PRE) * sr)
        n = min(len(seg), len(a) - i)
        a[i:i+n] += seg[:n] * 1.0
    a = a / (np.max(np.abs(a)) + 1e-9) * 0.95
    mix = r.SALIDA / f"{g['id']}-mix.wav"
    with wave.open(str(mix), 'w') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.stack([a, a], 1) * 32767).astype(np.int16).tobytes())
    tmp = r.SALIDA / f"{g['id']}-voz.tmp.mp4"
    p = subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{r.W}x{r.H}','-r',str(r.FPS),'-i','-',
                          '-i',str(mix),'-c:v','libx264','-preset','medium','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
                          '-af','loudnorm=I=-14:TP=-1.5:LRA=11','-shortest','-movflags','+faststart',str(tmp)], stdin=subprocess.PIPE)
    for f in range(int(total * r.FPS)):
        p.stdin.write(r.fotograma(g, f / r.FPS).tobytes())
    p.stdin.close()
    if p.wait() == 0:
        dest = Path('../bandeja'); dest.mkdir(exist_ok=True)
        nombre = f"datos-{g['id']}-" + __import__('datetime').datetime.utcnow().strftime('%Y%m%d-%H%M')
        tmp.rename(dest / f"{nombre}.mp4")
        (dest / f"{nombre}.json").write_text(json.dumps({"titulo": g.get('titulo', g['id']), "tipo": "datos"}, ensure_ascii=False))
    print(g['id'], round(total, 1), flush=True)
