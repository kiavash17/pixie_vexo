"""
Vexo band hello world: every sensor + the voice stream.

  python hello.py            real band (double-tap it first: light blinks blue)
  python hello.py --sim      pretend band, no hardware

Phase 1 (10 s): LED green, live accelerometer + gyro, taps/gestures, steps,
                battery, chip temperature, Bluetooth signal.
Phase 2 (10 s): microphone on (light goes solid blue), loudness meter,
                Opus voice packets saved to hello.ogg; live transcript if
                DEEPGRAM_API_KEY is set (env var or .env in this folder).
"""
import sys
from pathlib import Path

import certfix  # noqa: F401  (fixes HTTPS on this machine; see certfix.py)

KIT = Path(__file__).resolve().parent / "vexo-open-kit"
sys.path.insert(0, str(KIT / "python"))             # the vexo_open library
sys.path.insert(0, str(KIT / "examples" / "python"))  # ogg writer + speech helper

from vexo_open.sync import Band  # noqa: E402
from ogg_opus import OggOpusWriter  # noqa: E402
import speech  # noqa: E402

BAND = 6                         # our band: Vexo-HACK-06
SIM = "--sim" in sys.argv
transport = "sim" if SIM else "ble"

extra = {}
if SIM:                          # the pretend band has no mic: give it the kit's sample voice
    from vexo_open import audio
    extra["audio_packets"] = audio.ogg_packets(str(KIT / "dashboard" / "speech" / "sample-speech.opus"))

print("Connecting to Vexo-HACK-%02d%s..." % (BAND, " (pretend)" if SIM else ""))
band = Band.connect(BAND, transport, **extra)
print("Hello, %s! firmware %s" % (band.name, band.info.firmware))

# ------------------------------------------------------------ phase 1: motion & sensors
count = {"motion": 0}


def on_motion(m):
    count["motion"] += 1
    if count["motion"] % 5 == 0:   # 25 Hz stream, print 5 lines/s
        print("  accel g  x%+.2f y%+.2f z%+.2f | gyro deg/s  x%+7.1f y%+7.1f z%+7.1f"
              % (m.ax, m.ay, m.az, m.gx, m.gy, m.gz))


band.on("motion", on_motion)
band.on("event", lambda e: print("  * gesture:", e.kind))
band.on("activity", lambda a: print("  steps=%s cadence=%s state=%s" % (a.steps, a.cadence, a.state)))
band.on("battery", lambda b: print("  battery %s%% (%s)" % (b.percent, b.state)))
band.on("temperature", lambda t: print("  chip temp %.1f C" % t.celsius))
band.on("link", lambda l: print("  rssi", l.rssi, "dBm"))

band.set_led("#00ff00")
print("\n[phase 1] Move the band, tap it, double-tap it...")
band.configure(motion=25, events=True, activity=True, battery=True, temperature=True,
               link=True)
band.wait(10)
band.configure(motion=False, events=False, activity=False, temperature=False, link=False)

# ------------------------------------------------------------ phase 2: voice
ears = None
try:
    engine = speech.create()                       # Deepgram, needs DEEPGRAM_API_KEY
    engine.start(lambda text, final: print("  heard:", text) if final else None)
    ears = engine                                  # only once start() worked
    print("\nLive transcript via %s (audio is sent to Deepgram)." % ears.label)
except Exception as problem:                       # no key -> just record
    print("\nNo transcript (%s). Recording only." % problem)

ogg = OggOpusWriter(str(Path(__file__).resolve().parent / "hello.ogg"))


def on_audio(a):                                   # 50 Opus packets/s, 16 kHz mono, 20 ms each
    if ogg.frames < 10 * 50:
        ogg.write(a.seq, a.opus)
        if ears:
            ears.feed(a.opus, a.seq)


band.on("audio", on_audio)
band.on("mic-level", lambda m: print("  loudness |%-30s| rms %d dB"
                                     % ("#" * int(max(0, 52 - m.rms_db) * 30 / 40), m.rms_db)))
print("[phase 2] Mic on (light is solid blue). Say something for 10 seconds...")
band.configure(audio=True, mic_level=0.5)
band.wait(10)
band.configure(audio=False, mic_level=False)       # mic off, LED unlocked
ogg.close()
print("Saved %.1f s of voice to hello.ogg (%d packets lost)." % (ogg.seconds, ogg.lost))
if ears:
    print("Transcript:", ears.stop() or "(nothing heard)")

band.set_led("#ffffff", pattern="blink", period=300)
band.wait(1.5)
band.disconnect()
print("Bye!")
