"""
Pixie control room: one Python process holds the band, a browser page shows it all.

  python server.py          real band 06 (double-tap it first)
  python server.py --sim    pretend band
  then open http://127.0.0.1:8765

Band  --BLE-->  server.py  --WebSocket-->  browser (static/)
                   |-- Deepgram (key from .env, never sent to the page)
                   |-- recordings/*.ogg (every mic session)
"""
import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

import certfix  # noqa: F401  (HTTPS fix for this machine)

ROOT = Path(__file__).resolve().parent
KIT = ROOT / "vexo-open-kit"
sys.path[:0] = [str(KIT / "python"), str(KIT / "examples" / "python")]

from aiohttp import web, WSMsgType  # noqa: E402
from vexo_open import Band, VexoError  # noqa: E402
from vexo_open.audio import PcmDecoder, ogg_packets  # noqa: E402
from ogg_opus import OggOpusWriter  # noqa: E402
import speech  # noqa: E402

BAND = 6                                           # our band: Vexo-HACK-06
PORT = 8765
REC_DIR = ROOT / "recordings"
SENSORS = dict(motion=50, events=True, activity=True, battery=10, temperature=2, link=True)
DATA_EVENTS = ["motion", "event", "activity", "battery", "temperature", "link", "mic-level"]


class RoomSpeech(speech.DeepgramSpeech):
    """Deepgram tuned for a noisy room. The kit's engine only ends a sentence on
    speech_final (a silence), which never comes when the room is loud. Also end it on
    UtteranceEnd (based on word timing, works in noise) and on finished . ? ! pieces."""

    def __init__(self, **options):
        options.setdefault("utterance_end_ms", 1000)
        super().__init__(**options)

    def _message(self, message):
        kind = message.get("type")
        if kind == "UtteranceEnd":
            self._sentence_ends()
            return
        super()._message(message)
        if kind == "Results" and message.get("is_final") and self._parts and self._parts[-1][-1:] in ".?!":
            self._sentence_ends()


class Hub:
    def __init__(self, transport):
        self.transport = transport
        self.band = None
        self.clients = {}                          # websocket -> outgoing queue
        self.status = {"type": "status", "state": "idle", "band": "Vexo-HACK-%02d" % BAND,
                       "mic": False, "transcript": None, "message": ""}
        self.decoder = None
        self.ogg = None
        self.ears = None
        self.loop = None
        self.latest = {}                           # newest message of each type, for the monitor
        self.counts = {"motion": 0, "audio": 0}

    # ---------------------------------------------------------------- terminal monitor
    def on_data(self, name, m):
        self.latest[name] = m
        if name == "motion":
            self.counts["motion"] += 1
        elif name == "event":
            print("  [gesture] %s%s" % (m.get("kind"), " " + m["face"] if m.get("face") else ""))
        self.push(dict(m, type=name))

    async def monitor(self):
        """Once a second: one parsed line of everything the band sends."""
        while True:
            await asyncio.sleep(1.0)
            n_motion, n_audio = self.counts["motion"], self.counts["audio"]
            self.counts = {"motion": 0, "audio": 0}
            if self.status["state"] != "connected":
                continue
            L = self.latest
            parts = []
            if "motion" in L:
                m = L["motion"]
                parts.append("acc %+.2f %+.2f %+.2f g" % (m["ax"], m["ay"], m["az"]))
                if m.get("gx") is not None:
                    parts.append("gyro %+6.1f %+6.1f %+6.1f dps" % (m["gx"], m["gy"], m["gz"]))
            parts.append("%2d Hz" % n_motion)
            if self.status["mic"]:
                lvl = L.get("mic-level")
                parts.append("mic %s dB %2d pkt/s" % (lvl["rms_db"] if lvl else "--", n_audio))
            if "temperature" in L:
                parts.append("%.1fC" % L["temperature"]["celsius"])
            if "battery" in L:
                parts.append("bat %s%%" % L["battery"]["percent"])
            if "link" in L and L["link"].get("rssi") is not None:
                parts.append("rssi %s" % L["link"]["rssi"])
            if "activity" in L:
                parts.append("steps %s %s" % (L["activity"]["steps"], L["activity"]["state"]))
            parts.append("web %d" % len(self.clients))
            print(" | ".join(parts))

    def on_transcript(self, text, final):          # runs on the event loop
        if final:
            print("  [heard] %s" % text)
        self.push({"type": "transcript", "text": text, "final": final})

    # ---------------------------------------------------------------- to the browsers
    def push(self, obj):
        text = json.dumps(obj, default=str)
        for q in self.clients.values():
            if q.qsize() < 2000:                   # a stuck tab must not grow memory
                q.put_nowait(text)

    def push_bytes(self, data):
        for q in self.clients.values():
            if q.qsize() < 2000:
                q.put_nowait(bytes(data))

    def set_status(self, **changes):
        self.status.update(changes)
        self.push(self.status)
        if changes.get("message"):
            print("[status]", changes.get("state", ""), changes["message"])

    # ---------------------------------------------------------------- band
    async def connect(self):
        if self.status["state"] in ("connecting", "connected", "reconnecting"):
            return
        self.set_status(state="connecting", message="Looking for Vexo-HACK-%02d (double-tap it)..." % BAND)
        extra = {}
        if self.transport == "sim":                # pretend band speaks the kit's sample recording
            extra["audio_packets"] = ogg_packets(str(KIT / "dashboard" / "speech" / "sample-speech.opus"))
        try:
            band = await Band.connect(BAND, self.transport, auto_reconnect=True, **extra)
        except VexoError as e:
            self.set_status(state="error", message=str(e))
            return
        self.band = band
        for name in DATA_EVENTS:
            band.on(name, lambda m, name=name: self.on_data(name, m))
        band.on("audio", self.on_audio)
        band.on("reconnecting", lambda m: self.set_status(state="reconnecting", message="Link lost, reconnecting..."))
        band.on("reconnected", self.on_reconnected)
        band.on("disconnect", self.on_disconnect)
        await band.configure(**SENSORS)
        self.set_status(state="connected", message="Connected to %s (firmware %s)" % (band.name, band.info.firmware))
        await self.set_mic(True)

    def on_reconnected(self, m):
        self.decoder = PcmDecoder() if self.status["mic"] else None   # new stream: new decoder
        self.set_status(state="connected", message="Reconnected")

    def on_disconnect(self, m):
        self.band = None
        self.stop_audio_outputs()
        self.set_status(state="idle", mic=False, message="Band disconnected. Double-tap it and press Connect.")

    # ---------------------------------------------------------------- microphone
    async def set_mic(self, on):
        if not self.band:
            return
        if on and not self.status["mic"]:
            self.decoder = PcmDecoder()
            REC_DIR.mkdir(exist_ok=True)
            name = "session-%s.ogg" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            self.ogg = OggOpusWriter(str(REC_DIR / name))
            self.start_transcript()
            await self.band.configure(audio=True, mic_level=0.1)
            self.set_status(mic=True, recording=name, message="Mic on: band light is solid blue")
        elif not on and self.status["mic"]:
            await self.band.configure(audio=False, mic_level=False)
            self.stop_audio_outputs()
            self.set_status(mic=False, message="Mic off")
            self.push({"type": "recordings", "files": list_recordings()})

    def start_transcript(self):
        try:
            engine = speech.create(RoomSpeech)     # Deepgram; key from .env
            engine.start(lambda text, final: self.loop.call_soon_threadsafe(self.on_transcript, text, final))
            self.ears = engine
            self.status["transcript"] = engine.label
        except Exception as e:                     # no key / no internet: still record and plot
            self.ears = None
            self.status["transcript"] = None
            self.set_status(message="No live transcript: %s" % e)

    def stop_audio_outputs(self):
        ears, self.ears = self.ears, None
        if ears:                                   # stop() waits for the last words: off the loop
            self.loop.run_in_executor(None, ears.stop)
        if self.ogg:
            self.ogg.close()
            self.ogg = None
        self.decoder = None

    def on_audio(self, a):                         # 50 Opus packets/s, 16 kHz mono, 20 ms
        self.counts["audio"] += 1
        if self.ogg:
            self.ogg.write(a.seq, a.opus)
        if self.ears:
            try:
                self.ears.feed(a.opus, a.seq)
            except Exception as e:
                self.ears = None
                self.set_status(transcript=None, message="Transcript stopped: %s" % e)
        if self.decoder:
            pcm = self.decoder.feed(a)             # 320 samples of int16 LE
            if pcm:
                self.push_bytes(pcm)

    async def close(self):
        self.stop_audio_outputs()
        if self.band:
            await self.band.disconnect()


def list_recordings():
    if not REC_DIR.exists():
        return []
    return [f.name for f in sorted(REC_DIR.glob("*.ogg"), reverse=True)]


# -------------------------------------------------------------------- web
async def ws_handler(request):
    hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    q = asyncio.Queue()
    hub.clients[ws] = q
    q.put_nowait(json.dumps(hub.status))
    q.put_nowait(json.dumps({"type": "recordings", "files": list_recordings()}))

    async def writer():
        while True:
            item = await q.get()
            if isinstance(item, bytes):
                await ws.send_bytes(item)
            else:
                await ws.send_str(item)

    task = asyncio.ensure_future(writer())
    try:
        async for msg in ws:                       # commands from the page
            if msg.type != WSMsgType.TEXT:
                continue
            cmd = json.loads(msg.data)
            if cmd.get("cmd") == "connect":
                asyncio.ensure_future(hub.connect())
            elif cmd.get("cmd") == "mic":
                try:
                    await hub.set_mic(bool(cmd.get("on")))
                except VexoError as e:
                    hub.set_status(message=str(e))
    finally:
        task.cancel()
        hub.clients.pop(ws, None)
    return ws


async def on_startup(app):
    hub = app["hub"]
    hub.loop = asyncio.get_running_loop()
    print("Loading the sound decoder...")
    PcmDecoder()                                   # load av once, before the band streams
    asyncio.ensure_future(hub.connect())
    asyncio.ensure_future(hub.monitor())


async def no_cache(request, response):             # always serve the newest page code
    response.headers["Cache-Control"] = "no-store"


async def on_cleanup(app):
    await app["hub"].close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sim", action="store_true", help="pretend band")
    args = p.parse_args()
    os.chdir(ROOT)                                 # speech.py reads .env from the current folder
    app = web.Application()
    app["hub"] = Hub("sim" if args.sim else "ble")
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/", lambda r: web.FileResponse(ROOT / "static" / "index.html"))
    REC_DIR.mkdir(exist_ok=True)
    app.router.add_static("/recordings/", REC_DIR)
    app.router.add_static("/static/", ROOT / "static")
    app.on_response_prepare.append(no_cache)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print("Control room: http://127.0.0.1:%d" % PORT)
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    main()
