"""Make demo/assets/maya.ogg: a child's voice saying a help line, as band-format Ogg Opus (16 kHz,
20 ms packets, ~16 kbps), padded with silence so the pretend band's loop doesn't repeat it at once.
Uses Gemini TTS (GEMINI_API_KEY in .env). Run once; the file is committed with the demo.
Usage: python demo/make_voice.py"""
import base64
import io
import json
import sys
import urllib.request
import wave
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gemini  # noqa: E402  (keys + certfix)

LINE = "[a young child, a little worried, calling out] Mommy? Can you come to the swings? I need you."
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent"
body = {"contents": [{"parts": [{"text": LINE}]}],
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Leda"}}}}}
data = None
for key in gemini.keys():
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        part = json.load(urllib.request.urlopen(req, timeout=120))["candidates"][0]["content"]["parts"][0]["inlineData"]
        data = base64.b64decode(part["data"])
        break
    except Exception as e:
        print("TTS failed with one key:", e)
if data is None:
    sys.exit("no audio")

# WAV (or raw PCM) -> 16 kHz mono int16
with av.open(io.BytesIO(data)) as f:
    res = av.AudioResampler(format="s16", layout="mono", rate=16000)
    pcm = np.concatenate([r.to_ndarray().reshape(-1) for fr in f.decode(audio=0) for r in res.resample(fr)])
pcm = np.concatenate([np.zeros(8000, np.int16), pcm, np.zeros(16000 * 12, np.int16)])   # 0.5 s + line + 12 s quiet

out_path = ROOT / "demo" / "assets" / "maya.ogg"
out_path.parent.mkdir(parents=True, exist_ok=True)
out = av.open(str(out_path), "w", format="ogg")
st = out.add_stream("libopus", rate=16000, options={"frame_duration": "20", "application": "voip"})
st.layout = "mono"
st.bit_rate = 16000
for i in range(0, len(pcm) - 320 + 1, 320):
    fr = av.AudioFrame.from_ndarray(pcm[i:i + 320].reshape(1, -1), format="s16", layout="mono")
    fr.sample_rate, fr.pts = 16000, i
    for p in st.encode(fr):
        out.mux(p)
for p in st.encode(None):
    out.mux(p)
out.close()
print("wrote %s (%.1f s)" % (out_path, len(pcm) / 16000))
