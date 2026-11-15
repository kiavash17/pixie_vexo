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
import io
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
from pixie import Pixie  # noqa: E402
import collections  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402

BAND = 6                                           # our band: Vexo-HACK-06
PORT = 8765
REC_DIR = ROOT / "recordings"
SENSORS = dict(motion=50, events=True, activity=0.5, battery=10, temperature=2, link=True)   # steps 2x/s
PIXIE_COMMANDS = {"ack", "resolve", "label", "hug", "find", "simulate", "fall_check", "listen", "call", "wallet", "clear_history",
                  "quiet_check", "nudge_dismiss", "day", "listen_in", "gesture",
                  "captions", "todo_done", "todo_delete", "trends", "enroll_voice"}
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


class _KeepOpen(io.BytesIO):
    def close(self):                               # OggOpusWriter.close() closes its file
        pass


class Hub:
    def __init__(self, transport):
        self.transport = transport
        self.sim_audio = None
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
        self.motion_hist = collections.deque(maxlen=600)   # (time, |a| in g), ~12 s at 50 Hz
        self.packets = collections.deque(maxlen=50 * 60)  # (time, seq, opus): last 60 s, RAM only
        self.levels = collections.deque(maxlen=600)        # (time, rms_db) from mic-level
        self.steps_hist = collections.deque(maxlen=20)     # (time, lifetime steps) from activity
        self.pixie = Pixie(self, ROOT / ("data-sim" if transport == "sim" else "data"))   # keep tests apart

    # ---------------------------------------------------------------- rolling audio buffer
    def clip(self, seconds, end=None):
        """Ogg Opus bytes of the last `seconds` of mic audio (from the RAM buffer)."""
        end = end or time.time()
        chosen = [(s, o) for t, s, o in list(self.packets) if end - seconds <= t <= end]
        if not chosen:
            return b""
        buf = _KeepOpen()
        w = OggOpusWriter(buf)
        first = chosen[0][0]
        for s, o in chosen:
            w.write((s - first) & 0xFFFF, o)
        w.close()                                  # writes the last page; buffer stays readable
        return buf.getvalue()

    def clip_pcm(self, seconds, end=None):
        """The same audio as clip(), decoded to int16 samples at 16 kHz (for loudness per word)."""
        end = end or time.time()
        chosen = [(s, o) for t, s, o in list(self.packets) if end - seconds <= t <= end]
        if not chosen:
            return []
        dec = PcmDecoder()
        out = bytearray()
        for s, o in chosen:
            out += dec.feed(o, s) or b""
        out += dec.flush() or b""
        import array
        samples = array.array("h")
        samples.frombytes(bytes(out[: len(out) // 2 * 2]))
        return samples

    def save_clip(self, name, seconds, end=None):
        data = self.clip(seconds, end)
        if data:
            REC_DIR.mkdir(exist_ok=True)
            (REC_DIR / name).write_bytes(data)
            self.push({"type": "recordings", "files": list_recordings()})
        return bool(data)

    def loudest_db(self, seconds):
        """Smallest rms_db (= loudest) in the last `seconds`, or None."""
        vals = [db for t, db in list(self.levels) if time.time() - t <= seconds]
        return min(vals) if vals else None

    # ---------------------------------------------------------------- terminal monitor
    def on_data(self, name, m):
        self.latest[name] = m
        if name == "mic-level":
            self.levels.append((time.time(), m["rms_db"]))
        elif name == "activity" and m.get("steps") is not None:
            self.steps_hist.append((time.time(), m["steps"]))
        if name == "motion":
            self.counts["motion"] += 1
            self.motion_hist.append((time.time(), math.sqrt(m["ax"] ** 2 + m["ay"] ** 2 + m["az"] ** 2)))
        elif name == "event":
            print("  [gesture] %s%s" % (m.get("kind"), " " + m["face"] if m.get("face") else ""))
        self.push(dict(m, type=name))
        self.pixie.on_data(name, m)

    def live_activity(self):
        """Still / walk / run from the last 2 s of motion: reacts in ~1 s, unlike the band's own
        activity classifier. Wrist swing while walking moves |a| by ~0.05-0.3 g; running more."""
        now = time.time()
        recent = [g for t, g in list(self.motion_hist) if now - t < 2.0]
        steps = [s for t, s in list(self.steps_hist) if now - t < 3.0]
        stepping = len(steps) >= 2 and steps[-1] > steps[0]          # new steps counted in the last 3 s
        if len(recent) < 20:
            return "walk" if stepping else (self.latest.get("activity") or {}).get("state")
        mean = sum(recent) / len(recent)
        dev = sum(abs(g - mean) for g in recent) / len(recent)
        state = "still" if dev < 0.04 else "walk" if dev < 0.35 else "run"
        return "walk" if state == "still" and stepping else state

    def motion_context(self):
        """What the wearer's body was doing in the 10 s before now, for the alert and the AI."""
        recent = [g for t, g in self.motion_hist if time.time() - t < 10]
        act = self.latest.get("activity") or {}
        if not recent:
            return {"activity": act.get("state"), "peak_g": None, "movement": "unknown"}
        peak = max(recent)
        jitter = sum(abs(g - 1.0) for g in recent) / len(recent)
        movement = "still" if jitter < 0.05 else "moving" if jitter < 0.3 else "vigorous / shaking"
        return {"activity": act.get("state"), "peak_g": round(peak, 2), "movement": movement}

    async def monitor(self):
        """Once a second: one parsed line of everything the band sends."""
        while True:
            await asyncio.sleep(1.0)
            n_motion, n_audio = self.counts["motion"], self.counts["audio"]
            self.counts = {"motion": 0, "audio": 0}
            self.pixie.tick()                      # day record + quiet-time check
            self.pixie.publish()                   # mom view: status, last seen, timers
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
        self.pixie.on_text(text, final)

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
    async def keep_connected(self):
        """Keep looking for OUR band (Vexo-HACK-NN only) whenever it is not connected, so a
        double-tap is all it takes: no server restart, no Connect button."""
        while True:
            if self.status["state"] in ("idle", "error"):
                await self.connect(quiet=True)
            await asyncio.sleep(3)

    async def connect(self, quiet=False):
        if self.status["state"] in ("connecting", "connected", "reconnecting"):
            return
        if quiet:                                  # background retry: don't repeat the same lines in the terminal
            self.status["state"] = "connecting"
            self.push(self.status)
        else:
            self.set_status(state="connecting", message="Looking for Vexo-HACK-%02d (double-tap it)..." % BAND)
        extra = {}
        if self.transport == "sim":                # pretend band speaks the kit's sample recording
            extra["audio_packets"] = ogg_packets(self.sim_audio or str(KIT / "dashboard" / "speech" / "sample-speech.opus"))
        try:
            band = await Band.connect(BAND, self.transport, auto_reconnect=True, **extra)
        except VexoError as e:
            msg = "%s (Pixie keeps trying: just double-tap the band)" % e
            if quiet and msg == self.status.get("message"):
                self.status["state"] = "error"
                self.push(self.status)
            else:
                self.set_status(state="error", message=msg)
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
        self.pixie.on_connection(True)             # mic stays off: Pixie opens it only after a help request

    def on_reconnected(self, m):
        self.decoder = PcmDecoder() if self.status["mic"] else None   # new stream: new decoder
        self.set_status(state="connected", message="Reconnected")
        self.pixie.on_connection(True)

    def on_disconnect(self, m):
        self.band = None
        self.stop_audio_outputs()
        self.set_status(state="idle", mic=False, message="Band disconnected. Double-tap it and press Connect.")
        self.pixie.on_connection(False)

    # ---------------------------------------------------------------- microphone
    async def set_mic(self, on, name=None, record=True):
        """Mic on: live transcript, plus a file recordings/<name> when record=True
        (Listening mode uses record=False: audio stays in the 60 s RAM buffer only).
        Mic off: returns the final transcript of that mic session."""
        if not self.band:
            return None
        if on and not self.status["mic"]:
            self.decoder = PcmDecoder()
            REC_DIR.mkdir(exist_ok=True)
            name = name or "session-%s.ogg" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            self.ogg = OggOpusWriter(str(REC_DIR / name)) if record else None
            self.start_transcript()
            await self.band.configure(audio=True, mic_level=0.1)
            self.set_status(mic=True, recording=name if record else None,
                            message="Mic on: band light is solid blue")
        elif not on and self.status["mic"]:
            await self.band.configure(audio=False, mic_level=False)
            ears, self.ears = self.ears, None
            self.stop_audio_outputs()
            text = ""
            if ears:
                try:
                    text = await self.loop.run_in_executor(None, ears.stop)
                except Exception as e:
                    print("  transcript stop: %s" % e)
            self.set_status(mic=False, message="Mic off")
            self.push({"type": "recordings", "files": list_recordings()})
            return text
        return None

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
        self.packets.append((time.time(), a.seq, bytes(a.opus)))
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
    q.put_nowait(json.dumps(hub.pixie.snapshot(), default=str))

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
            elif cmd.get("cmd") in PIXIE_COMMANDS:
                try:
                    await hub.pixie.command(cmd)
                except Exception as e:
                    print("  [pixie] command %s failed: %s" % (cmd.get("cmd"), e))
    finally:
        task.cancel()
        hub.clients.pop(ws, None)
    return ws


async def on_startup(app):
    hub = app["hub"]
    hub.loop = asyncio.get_running_loop()
    print("Loading the sound decoder...")
    PcmDecoder()                                   # load av once, before the band streams
    asyncio.ensure_future(hub.keep_connected())    # first try now, then again whenever the band is not connected
    asyncio.ensure_future(hub.monitor())
    asyncio.ensure_future(hub.pixie.listen_loop())
    asyncio.ensure_future(hub.pixie.actions_loop())
    asyncio.ensure_future(hub.pixie.voice_loop())


async def transcript_handler(request):
    """The full-day transcript: /api/transcript?which=today|typical|rough (or date=YYYY-MM-DD)."""
    import daylog
    pixie = request.app["hub"].pixie
    which = request.query.get("which", "today")
    if which in ("typical", "rough"):
        lines = daylog.sample_transcript(which)
    else:
        lines = pixie.transcripts.lines(request.query.get("date"))
    return web.json_response({"which": which, "lines": lines})


async def no_cache(request, response):             # always serve the newest page code
    response.headers["Cache-Control"] = "no-store"


async def on_cleanup(app):
    await app["hub"].close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sim", action="store_true", help="pretend band")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--sim-audio", help="Ogg Opus file the pretend band plays as its microphone")
    args = p.parse_args()
    os.chdir(ROOT)                                 # speech.py reads .env from the current folder
    app = web.Application()
    app["hub"] = Hub("sim" if args.sim else "ble")
    app["hub"].sim_audio = args.sim_audio
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/", lambda r: web.FileResponse(ROOT / "static" / "index.html"))
    app.router.add_get("/mom", lambda r: web.FileResponse(ROOT / "static" / "mom.html"))
    app.router.add_get("/shop", lambda r: web.FileResponse(ROOT / "static" / "shop.html"))
    app.router.add_get("/api/transcript", transcript_handler)
    REC_DIR.mkdir(exist_ok=True)
    app.router.add_static("/recordings/", REC_DIR)
    app.router.add_static("/static/", ROOT / "static")
    app.on_response_prepare.append(no_cache)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    print("Control room: http://127.0.0.1:%d   Mom view: http://127.0.0.1:%d/mom" % (args.port, args.port))
    web.run_app(app, host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":
    main()
