"""Generate Pixie test scenes with Gemini TTS -> WAV (24 kHz) and one combined Ogg Opus (16 kHz, 20 ms)
for the pretend band. Usage: make_test_audio.py OUT_DIR"""
import base64
import json
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import gemini  # noqa: E402  (key loading + certfix)

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
MODEL = "gemini-3.8-flash-tts"
URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % MODEL

SCENES = [  # name, expected, speakers {name: voice}, script
    ("calm", "nothing", {"Mom": "Kore", "Kid": "Leda"},
     "(direction)\n"
     "Mom: [warm, relaxed] Do you want the apple or the banana, honey?\n"
     "Kid: [cheerful] Banana please! Can I go on the swings after?\n"
     "Mom: [relaxed] Sure, I'll be right here on the bench."),
    ("teacher", "nothing (normal adult instructions)", {"Teacher": "Charon", "Kid": "Leda"},
     "(direction)\n"
     "Teacher: [friendly, upbeat] Okay everyone, line up by the door and hold your buddy's hand.\n"
     "Kid: [excited] Can I be line leader?\n"
     "Teacher: [friendly] Sure, Maya, lead us to the bus. Stay with the group."),
    ("angry_adult", "adult_anger", {"Man": "Fenrir", "Kid": "Leda"},
     "(direction)\n"
     "Man: [shouting furiously] What did I just tell you?! Get over here RIGHT NOW!\n"
     "Kid: [frightened, small voice] I'm sorry, I'm sorry...\n"
     "Man: [yelling aggressively] Don't you dare walk away from me! I am sick of this!"),
    ("scared_child", "crying / distress", {"Kid": "Leda", "Man": "Charon"},
     "(direction)\n"
     "Kid: [sobbing, panicked, voice shaking] Mommy? Mommy where are you? I can't find you... I'm scared!\n"
     "Kid: [crying hard] Mommy! Please... I want my mommy!"),
    ("luring", "adult_concerning", {"Man": "Algenib", "Kid": "Leda"},
     "(direction)\n"
     "Man: [soft, overly friendly, coaxing] Hey sweetie, are you here all by yourself?\n"
     "Kid: [unsure] Um... my mom is over there somewhere.\n"
     "Man: [whispering, coaxing] I've got some puppies in my van, do you want to see them? "
     "It'll be our little secret, okay? Don't tell your mom.\n"
     "Kid: [hesitant] I'm not supposed to go with strangers...\n"
     "Man: [smooth, pressuring] It's okay, your mom said it's fine. She asked me to come get you. "
     "Come on, quick, before she worries."),
]


def tts(script, speakers):
    voices = [{"speaker": n, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}} for n, v in speakers.items()]
    direction, *lines = script.split("\n")
    parts = []
    for line in lines:
        who, _, said = line.partition(": ")
        parts.append({"text": said, "speech_metadata": {"speaker": who}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": voices}}}}
    for key in gemini.keys():
        req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                     headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        try:
            out = json.load(urllib.request.urlopen(req, timeout=120))
            part = out["candidates"][0]["content"]["parts"][0]["inlineData"]
            return base64.b64decode(part["data"]), part["mimeType"]
        except urllib.error.HTTPError as e:
            print("   HTTP", e.code, e.read()[:200].decode(errors="replace"))
    raise SystemExit("TTS failed")


manifest = []
for name, expected, speakers, script in SCENES:
    pcm, mime = tts(script, speakers)
    rate = int(mime.split("rate=")[1].split(";")[0]) if "rate=" in mime else 24000
    path = OUT / ("%s.wav" % name)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    secs = len(pcm) / 2 / rate
    manifest.append({"name": name, "expected": expected, "file": str(path), "seconds": round(secs, 1)})
    print("%-13s %5.1f s  %s  (%s)" % (name, secs, path.name, mime))
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
