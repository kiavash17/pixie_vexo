"""Make the showcase voice-over: one WAV per line in demo/assets/vo/ plus vo.json (seconds per line).
A warm woman's voice (Gemini TTS, voice "Sulafat") in the tone of a feel-good family ad.
Uses GEMINI_API_KEY from .env. Run once (or after changing a line); the files are committed.
Usage: python demo/make_voiceover.py [line-id ...]"""
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

VOICE = "Sulafat"
STYLE = "[a warm, friendly woman narrating a feel-good family TV ad; smiling, calm and reassuring, unhurried]"
RATE = 24000
LINES = {
    "intro": "Meet Pixie: a little band for your child's wrist. No screen. Just peace of mind. Here are ten things it does for you.",
    "f1": "If an adult says something worrying, you'll know right away, with their exact words.",
    "f2": "When Maya calls out for you, Pixie hears it. No button needed.",
    "f3": "Crying, or an angry voice nearby? Each moment has its own colour, so you know at a glance.",
    "f4": "If she falls, the band asks if she's OK. One double-tap, and you can breathe again.",
    "f5": "Live captions let you read what's being said around her, as it happens.",
    "f6": "When her teacher says, \"tell your mom to pack a lunch,\" it lands right on your to-do list.",
    "f7": "She can pay for treats with a tap. Small things just work, and anything bigger asks you first.",
    "f8": "If she's been quiet on her own for a while, Pixie sends a gentle nudge. Maybe send her a hug.",
    "f9": "Every evening, a picture of Maya's day, with an honest note and simple next steps.",
    "f10": "And over the weeks, Pixie gently spots patterns, compared with Maya's own normal.",
    "outro": "Pixie. More freedom for them. More peace of mind for you.",
}
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-tts:generateContent"
OUT = ROOT / "demo" / "assets" / "vo"


def speak(text):
    body = {"contents": [{"parts": [{"text": "%s %s" % (STYLE, text)}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}}}
    for key in gemini.keys():
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        try:
            part = json.load(urllib.request.urlopen(req, timeout=120))["candidates"][0]["content"]["parts"][0]["inlineData"]
            data = base64.b64decode(part["data"])
            break
        except Exception as e:
            print("  TTS failed with one key:", e)
    else:
        sys.exit("no audio")
    if data[:4] == b"RIFF":
        with av.open(io.BytesIO(data)) as f:
            res = av.AudioResampler(format="s16", layout="mono", rate=RATE)
            pcm = np.concatenate([r.to_ndarray().reshape(-1) for fr in f.decode(audio=0) for r in res.resample(fr)])
    else:                                              # raw 24 kHz 16-bit PCM
        pcm = np.frombuffer(data, np.int16)
    loud = np.nonzero(np.abs(pcm) > 400)[0]            # trim silence at both ends
    if len(loud):
        pcm = pcm[max(0, loud[0] - 1200):loud[-1] + 2400]
    return pcm


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "vo.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    for k in sys.argv[1:] or LINES:
        expect = len(LINES[k].split()) / 2.6 + 1.5        # sometimes the model reads the style note aloud: retry
        for _ in range(4):
            pcm = speak(LINES[k])
            if len(pcm) / RATE <= expect * 1.35:
                break
            print("  %s: %.1f s, longer than expected (%.1f s), trying again" % (k, len(pcm) / RATE, expect))
        with wave.open(str(OUT / ("%s.wav" % k)), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
        meta[k] = round(len(pcm) / RATE, 2)
        print("%-5s %.1f s  %s" % (k, meta[k], LINES[k]))
    meta_path.write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
