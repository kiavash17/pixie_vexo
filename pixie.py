"""
Pixie engine: the guardian loop on top of the band.

  double-tap ──> HELP event ──> guardian alert (mom view) ──> COMING ──> band glows green
      │              │                 │
      │              ├─ voice note (mic on for NOTE_SECONDS, then off) ─> transcript
      │              ├─ AI assistant: summary + urgency (can only RAISE the rule level)
      │              └─ no answer in ACK_TIMEOUT ─> louder + second guardian ─> call (simulated)
      └─ again while active ──> URGENT

  free-fall ──> "are you OK?" (magenta blink) ──> double-tap = OK, else HELP (urgent)

Rules are transparent and always win. Everything is logged to data/events.json with the
guardian's outcome label (accidental / wanted me / urgent) for later learning.
"""
import asyncio
import collections
import json
import time
from pathlib import Path

import gemini

CHILD = "Maya"
GUARDIANS = [{"name": "Mom", "role": "primary"}, {"name": "Dad", "role": "secondary"}]
NOTE_SECONDS = 8          # mic open after a help request
ACK_TIMEOUT = 30          # seconds without an answer before each escalation step
FALL_CHECK_SECONDS = 15   # time to answer "are you OK?" with a double-tap
DEBOUNCE = 1.5            # ignore a second double-tap closer than this
LOW_BATTERY = 15

LED = {                                   # (colour, pattern, period ms); mic-on = solid blue (band rule)
    "waiting": ("#ffaa00", "breathe", 1500),   # amber: sent, waiting for an answer
    "urgent": ("#ff2200", "blink", 400),       # red: urgent, waiting
    "coming": ("#00ff55", "breathe", 1000),    # green: help is coming
    "ruok": ("#ff00ff", "blink", 500),         # magenta: are you OK?
    "hug": ("#ff66cc", "breathe", 1200),       # pink: guardian sent a hug
    "ok": ("#ffffff", "flash", 300),           # white flash: resolved
}
URGENT_WORDS = ("hurt", "help", "lost", "scared", "stranger", "bleeding", "fell", "fall", "can't find",
                "emergency", "pain", "afraid", "crying", "come now", "hurry")
OUTCOMES = ("accidental", "wanted me", "urgent", "ok")

# Listening mode (Gemini hears 5 s windows; only windows with sound are sent)
WINDOW = 5
GATE_DB = 42              # send a window only if its loudest rms_db is <= this (lower = louder; quiet room ~50)
THRESH = {"screaming": 0.6, "adult_anger": 0.6, "crying": 0.6, "adult_concerning": 0.6}
CONTEXT_SECONDS = 120     # recent transcript sent with every window (luring builds over time)
CONCERN_CLIP = 60         # whole RAM buffer kept when an adult's behaviour is concerning
STRONG = 0.85             # one window this sure is enough; otherwise 2 of the last 3 windows
ANGER_NOTE = 0.4          # any sign of adult anger is logged with its clip, even below the alert level
CLIP_BEFORE, CLIP_AFTER = 30, 20
DETECTIONS = {            # signal -> (reason for the parent, level)
    "screaming": ("Pixie heard screaming near %s", 2),
    "adult_anger": ("Pixie heard an angry adult voice near %s", 2),
    "crying": ("Pixie heard %s crying", 1),
    "adult_concerning": ("An adult is saying concerning things to %s", 2),
}


class Pixie:
    def __init__(self, hub, data_dir: Path):
        self.hub = hub
        self.file = data_dir / "events.json"
        data_dir.mkdir(exist_ok=True)
        self.history = json.loads(self.file.read_text()) if self.file.exists() else []
        self.active = None
        self.tasks = []
        self.last_tap = 0.0
        self.led_state = None             # what the band should show once the mic is off
        self.fall_check = True
        self.notice = None                # trust-layer banner: offline / low battery
        self.last_seen = None
        self.steps_start = None
        self.rec_dir = data_dir.parent / "recordings"
        self.listening = False
        self.listen = {"last": None, "t": None, "quiet": True, "error": None}
        self.recent = collections.deque(maxlen=3)
        self.convo = collections.deque(maxlen=60)          # (time, words) heard in listening mode
        self.last_anger_note = 0.0

    # ================================================================ snapshot for the page
    def snapshot(self):
        L, st = self.hub.latest, self.hub.status
        rssi = (L.get("link") or {}).get("rssi")
        act = L.get("activity") or {}
        bat = L.get("battery") or {}
        if self.steps_start is None and act.get("steps") is not None:
            self.steps_start = act["steps"]
        return {
            "type": "pixie", "child": CHILD, "guardians": GUARDIANS, "ack_timeout": ACK_TIMEOUT,
            "band": {
                "connected": st["state"] == "connected", "state": st["state"], "name": st["band"],
                "battery": bat.get("percent"), "charging": bat.get("charging"),
                "rssi": rssi, "signal": signal_label(rssi), "activity": act.get("state"),
                "steps": (act["steps"] - self.steps_start) if act.get("steps") is not None else None,
                "last_seen": self.last_seen, "mic": st["mic"],
            },
            "notice": self.notice, "fall_check": self.fall_check,
            "listen": dict(self.listen, on=self.listening, gemini=gemini.available(),
                           requests_hour=gemini.requests_last_hour()),
            "active": self.active, "history": self.history[-30:][::-1],
        }

    def publish(self):
        self.hub.push(self.snapshot())

    # ================================================================ inputs from the band
    def on_data(self, name, m):
        self.last_seen = time.time()
        if name == "event" and self.hub.transport == "sim":
            return                       # pretend band taps by itself: use the demo buttons instead
        if name == "event":
            kind = m.get("kind")
            if kind == "double-tap":
                self.on_double_tap()
            elif kind == "free-fall" and self.fall_check:
                self.on_fall()
        elif name == "battery":
            if m.get("percent") is not None and m["percent"] <= LOW_BATTERY and not m.get("charging"):
                self.notice = "%s's band battery is low (%s%%)" % (CHILD, m["percent"])
            elif self.notice and "battery" in self.notice:
                self.notice = None
            self.publish()

    def on_connection(self, connected):
        if connected:
            if self.notice and "offline" in self.notice:
                self.notice = None
            self.log_line("Band back online")
            asyncio.ensure_future(self.apply_led())
            if self.listening and not self.hub.status["mic"]:
                asyncio.ensure_future(self.hub.set_mic(True, record=False))
        else:
            self.notice = "%s's band is offline: alerts can't reach you" % CHILD
            self.log_line("Band went offline")
        self.publish()

    def on_double_tap(self):
        now = time.time()
        if now - self.last_tap < DEBOUNCE:
            return
        self.last_tap = now
        a = self.active
        if a and a["state"] == "checking":                     # answer to "are you OK?"
            self.timeline("%s double-tapped: I'm OK" % CHILD)
            self.finish(outcome="ok")
            return
        if a and a["state"] in ("listening", "waiting", "coming"):
            if a["level"] < 2:
                self.raise_level(2, "%s double-tapped again" % CHILD)
            else:
                self.timeline("%s double-tapped again" % CHILD)
            self.publish()
            return
        self.start_help("double-tap", "%s double-tapped the band" % CHILD, level=1)

    def on_fall(self):
        if self.active:
            return
        self.active = self.new_event("fall", "Possible fall detected", level=1, state="checking")
        self.timeline("Possible fall: asking %s if everything is OK (magenta blink)" % CHILD)
        self.set_led("ruok")
        self.spawn(self.fall_timer(self.active["id"]))
        self.publish()

    async def fall_timer(self, eid):
        await asyncio.sleep(FALL_CHECK_SECONDS)
        a = self.active
        if a and a["id"] == eid and a["state"] == "checking":
            a["kind"] = "help"
            self.timeline("No answer in %d s after the fall" % FALL_CHECK_SECONDS)
            self.raise_level(2, "fall with no response")
            self.begin_alert()

    # ================================================================ help flow
    def new_event(self, kind, reason, level, state):
        return {"id": "%d" % (time.time() * 1000), "kind": kind, "level": level, "state": state,
                "reasons": [reason], "created": time.time(), "timeline": [], "transcript": "",
                "live_text": "", "audio": None, "ai": None, "escalation": 0, "acked_by": None,
                "acked_at": None, "resolved_at": None, "outcome": None,
                "context": self.hub.motion_context()}

    def start_help(self, trigger, reason, level):
        self.active = self.new_event("help", reason, level, "listening")
        self.timeline(reason)
        self.begin_alert()

    def begin_alert(self):
        a = self.active
        a["state"] = "listening"
        self.timeline("Alert sent to %s; listening to %s for %d s" % (GUARDIANS[0]["name"], CHILD, NOTE_SECONDS))
        self.publish()
        self.spawn(self.voice_note(a["id"]))
        self.spawn(self.escalation(a["id"]))

    async def voice_note(self, eid):
        audio_name = "help-%s.ogg" % eid
        text = ""
        if self.listening:                                   # mic already on: cut the note from the buffer
            await asyncio.sleep(NOTE_SECONDS)
            self.hub.save_clip(audio_name, NOTE_SECONDS + 2)
        else:
            try:
                await self.hub.set_mic(True, name=audio_name)
            except Exception as e:
                self.timeline("Voice note unavailable: %s" % e)
            await asyncio.sleep(NOTE_SECONDS)
            try:
                text = await self.hub.set_mic(False) or ""
            except Exception as e:
                self.timeline("Mic problem: %s" % e)
        a = self.active
        if not a or a["id"] != eid:
            return
        # words heard during this alert (on_text); the session text only as a fallback
        a["transcript"] = (a["transcript"] or text).strip() or a["live_text"].strip()
        a["live_text"] = ""
        a["audio"] = audio_name
        if a["state"] == "listening":
            a["state"] = "waiting"
        self.timeline('Voice note: "%s"' % a["transcript"] if a["transcript"] else "Voice note: nothing said")
        await self.apply_led()
        self.publish()
        await self.assess(eid)

    def on_text(self, text, final):                          # live transcript during the note
        a = self.active
        if a and a["state"] in ("listening", "coming", "waiting") and self.hub.status["mic"]:
            if final:
                a["transcript"] = (a["transcript"] + " " + text).strip()
                a["live_text"] = ""
            else:
                a["live_text"] = text
            self.publish()

    async def assess(self, eid):
        a = self.active
        facts = {
            "child": CHILD, "trigger": a["reasons"], "voice_note": a["transcript"] or "(silence)",
            "motion_before_alert": a["context"],
            "past_week": history_stats(self.history),
            "local_time": time.strftime("%H:%M"),
        }
        clip = self.rec_dir / a["audio"] if a.get("audio") else None
        audio = clip.read_bytes() if clip and clip.exists() else b""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, assess_chain, facts, audio)
        a = self.active
        if not a or a["id"] != eid:
            return
        a["ai"] = result
        if result.get("children") is not None:
            a["voices"] = {"children": result["children"], "adults": result["adults"]}
        if not a["transcript"] and result.get("transcript"):
            a["transcript"] = result["transcript"]
        who = SOURCE_NAMES.get(result["source"], result["source"])
        self.timeline("%s: %s" % (who, result["summary"]))
        if result["urgency"] == "urgent" and a["level"] < 2:
            self.raise_level(2, "%s: %s" % (who, result["why"]))
        self.publish()

    async def escalation(self, eid):
        steps = [
            "No answer in %ds: louder alert, %s notified" % (ACK_TIMEOUT, GUARDIANS[1]["name"]),
            "Still no answer: automated call to %s and %s (simulated)" % (GUARDIANS[0]["name"], GUARDIANS[1]["name"]),
        ]
        for i, text in enumerate(steps, 1):
            await asyncio.sleep(ACK_TIMEOUT)
            a = self.active
            if not a or a["id"] != eid or a["state"] not in ("listening", "waiting"):
                return
            a["escalation"] = i
            self.timeline(text)
            self.publish()

    def raise_level(self, level, why):
        a = self.active
        if a and level > a["level"]:
            a["level"] = level
            a["reasons"].append(why)
            self.timeline("URGENT: %s" % why)
            asyncio.ensure_future(self.apply_led())

    # ================================================================ guardian actions
    async def command(self, cmd):
        c = cmd.get("cmd")
        a = self.active
        if c == "ack" and a and a["state"] in ("listening", "waiting", "checking"):
            a["state"], a["acked_by"], a["acked_at"] = "coming", cmd.get("by", GUARDIANS[0]["name"]), time.time()
            self.timeline("%s: I'm coming! (band glows green)" % a["acked_by"])
            if self.listening:
                self.spawn(self.pause_for_led())             # mic locks the light: pause to show green
            else:
                await self.apply_led()
        elif c == "listen":
            await self.set_listening(bool(cmd.get("on")))
        elif c == "resolve" and a:
            self.timeline("%s marked it resolved" % cmd.get("by", GUARDIANS[0]["name"]))
            self.finish(outcome=cmd.get("outcome"))
        elif c == "label":
            for e in self.history:
                if e["id"] == cmd.get("id") and cmd.get("outcome") in OUTCOMES:
                    e["outcome"] = cmd["outcome"]
            self.save()
        elif c == "hug":
            await self.flash_led("hug", 4)
            self.log_line("%s sent %s a hug (pink glow)" % (GUARDIANS[0]["name"], CHILD))
        elif c == "find" and self.hub.band and not self.hub.status["mic"]:
            await self.hub.band.identify(5)
        elif c == "simulate":
            if cmd.get("what") == "double-tap":
                self.last_tap = 0
                self.on_double_tap()
            elif cmd.get("what") == "fall":
                self.on_fall()
            elif cmd.get("what") in ("crying", "screaming", "adult_anger", "adult_concerning"):
                k = cmd["what"]
                fake = {"crying": 0.1, "screaming": 0.1, "adult_anger": 0.1, "adult_concerning": 0.0,
                        "concern": "(simulated) asked the child to keep a secret and come to the car"
                        if k == "adult_concerning" else "", "child_distress": 0.8,
                        "children": 1, "adults": 1 if k.startswith("adult") else 0, "transcript": "",
                        "evidence": "(simulated %s from the demo button)" % k.replace("_", " ")}
                fake[k] = 0.95
                self.on_listen(fake)
        elif c == "fall_check":
            self.fall_check = bool(cmd.get("on"))
        self.publish()

    def finish(self, outcome=None):
        a, self.active = self.active, None
        for t in self.tasks:
            t.cancel()
        self.tasks = []
        if self.hub.status["mic"] and not self.listening:
            asyncio.ensure_future(self.hub.set_mic(False))
        self.recent.clear()                  # a new alert needs fresh evidence, not the windows just handled
        a["state"], a["resolved_at"] = "resolved", time.time()
        if outcome in OUTCOMES:
            a["outcome"] = outcome
        a.pop("live_text", None)
        self.history.append(a)
        self.save()
        asyncio.ensure_future(self.flash_led("ok", 1.5, then=None))
        self.publish()

    # ================================================================ helpers
    def timeline(self, text):
        if self.active is not None:
            self.active["timeline"].append({"t": time.time(), "text": text})
        print("  [pixie] %s" % text)

    def log_line(self, text, audio=None, extra=None):        # a note outside any alert
        note = {"id": "%d" % (time.time() * 1000), "kind": "note", "created": time.time(),
                "reasons": [text], "timeline": [], "state": "note", "audio": audio}
        note.update(extra or {})
        self.history.append(note)
        self.save()
        print("  [pixie] %s" % text)

    # ================================================================ listening mode
    async def set_listening(self, on):
        if on and not self.listening:
            if not gemini.available():
                self.notice = "Listening mode needs GEMINI_API_KEY in .env"
                return
            self.listening = True
            self.recent.clear()
            await self.hub.set_mic(True, record=False)
            self.log_line("Listening mode on: Pixie listens for crying, screaming and angry voices (blue light)")
        elif not on and self.listening:
            self.listening = False
            if not (self.active and self.active["state"] == "listening"):
                await self.hub.set_mic(False)
            self.listen.update(last=None, quiet=True)
            self.log_line("Listening mode off")
            await self.apply_led()

    async def pause_for_led(self, seconds=4):
        """The band refuses light commands while the mic is on: pause listening briefly."""
        await self.hub.set_mic(False)
        await self.apply_led()
        await asyncio.sleep(seconds)
        if self.listening and self.hub.band:
            await self.hub.set_mic(True, record=False)

    async def listen_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(WINDOW)
            if not (self.listening and self.hub.status["mic"]):
                continue
            loud = self.hub.loudest_db(WINDOW)
            if loud is None or loud > GATE_DB:               # quiet window: nothing sent
                self.listen.update(quiet=True, t=time.time(), loudest_db=loud)
                continue
            audio = self.hub.clip(WINDOW)
            if not audio:
                continue
            try:
                r = await loop.run_in_executor(None, gemini.analyze, audio, self.listen_prompt(),
                                               gemini.LISTEN_SCHEMA)
            except Exception as e:
                self.listen["error"] = str(e)[:120]
                print("  [listen] %s" % e)
                continue
            r["loudest_db"] = loud
            self.on_listen(r)

    def peak(self, key):
        """Strongest score for `key` in the recent windows (what triggered the alert)."""
        return max([x.get(key, 0.0) for x in self.recent] or [0.0])

    def listen_prompt(self):
        now = time.time()
        lines = ["[%ds ago] %s" % (now - t, w) for t, w in self.convo if now - t <= CONTEXT_SECONDS]
        return gemini.LISTEN_PROMPT % ("\n".join(lines) or "(nothing yet)")

    def on_listen(self, r):
        now = time.time()
        r["t"] = now
        r.setdefault("adult_concerning", 0.0)
        r.setdefault("concern", "")
        self.listen.update(last=r, t=now, quiet=False, error=None)
        self.recent.append(r)
        if r.get("transcript"):
            self.convo.append((now, r["transcript"]))
        print("  [listen] cry %.2f scream %.2f anger %.2f concern %.2f | %d child %d adult | %s"
              % (r["crying"], r["screaming"], r["adult_anger"], r["adult_concerning"], r["children"],
                 r["adults"], (r.get("concern") or r.get("evidence", ""))[:70]))

        def sustained(key):
            hits = [x for x in self.recent if x[key] >= THRESH[key] and now - x["t"] <= WINDOW * 3.5]
            return len(hits) >= 2 or r[key] >= STRONG

        found = [k for k in DETECTIONS if sustained(k)]
        if r["adult_anger"] >= ANGER_NOTE and "adult_anger" not in found and now - self.last_anger_note > 30:
            self.last_anger_note = now                       # any adult anger is recorded, even below alert level
            name = "anger-%d.ogg" % (now * 1000)
            self.hub.save_clip(name, 15)
            self.log_line("Raised adult voice near %s (%.0f%%): %s" % (CHILD, r["adult_anger"] * 100, r["evidence"]),
                          audio=name, extra={"signals": {k: r[k] for k in THRESH}})
        if found:
            self.on_distress(found, r)
        self.publish()

    def on_distress(self, found, r):
        level = max(DETECTIONS[k][1] for k in found)
        reasons = [DETECTIONS[k][0] % CHILD for k in found]
        a = self.active
        if a:                                                # already an alert: add the evidence
            for k, reason in zip(found, reasons):
                if reason not in a["reasons"]:
                    a["reasons"].append(reason)
                    self.timeline("%s (%.0f%%)" % (reason, self.peak(k) * 100))
            if level > a["level"]:
                self.raise_level(level, reasons[0])
            return
        a = self.new_event("distress", reasons[0], level, "waiting")
        a["reasons"] = reasons
        a["signals"] = {k: self.peak(k) for k in THRESH}
        a["voices"] = {"children": r["children"], "adults": r["adults"]}
        now = time.time()
        recent_words = " … ".join(w for t, w in self.convo if now - t <= CONTEXT_SECONDS)
        a["transcript"] = recent_words if "adult_concerning" in found else r.get("transcript", "")
        a["concern"] = r.get("concern", "")
        a["audio"] = "distress-%s.ogg" % a["id"]
        self.active = a
        before = CONCERN_CLIP if "adult_concerning" in found else CLIP_BEFORE
        self.hub.save_clip(a["audio"], before)
        for k, reason in zip(found, reasons):
            detail = r.get("concern") if k == "adult_concerning" and r.get("concern") else r.get("evidence", "")
            self.timeline("%s (%.0f%%): %s" % (reason, self.peak(k) * 100, detail))
        self.timeline("Alert sent to %s; clip of the last %d s saved" % (GUARDIANS[0]["name"], before))
        self.publish()
        self.spawn(self.extend_clip(a["id"], a["audio"]))
        self.spawn(self.assess(a["id"]))
        self.spawn(self.escalation(a["id"]))

    async def extend_clip(self, eid, name):
        await asyncio.sleep(CLIP_AFTER)                      # keep what happened right after, too
        if self.hub.save_clip(name, CLIP_BEFORE + CLIP_AFTER):
            for e in ([self.active] if self.active else []) + self.history[-5:]:
                if e and e.get("id") == eid:
                    e.setdefault("timeline", []).append({"t": time.time(), "text": "Clip extended to %d s"
                                                         % (CLIP_BEFORE + CLIP_AFTER)})
            self.publish()

    def spawn(self, coro):
        self.tasks.append(asyncio.ensure_future(coro))

    def save(self):
        self.file.write_text(json.dumps(self.history[-500:], indent=1))

    def desired_led(self):
        a = self.active
        if not a:
            return None
        if a["state"] == "checking":
            return "ruok"
        if a["state"] == "coming":
            return "coming"
        return "urgent" if a["level"] >= 2 else "waiting"

    def set_led(self, state):
        self.led_state = state
        asyncio.ensure_future(self.apply_led())

    async def apply_led(self):
        """Show what the alert state calls for. While the mic is on the band keeps its
        light solid blue and refuses LED commands; the voice note re-applies afterwards."""
        band = self.hub.band
        if not band or self.hub.status["mic"]:
            return
        want = self.desired_led() if self.active else None
        try:
            if want:
                colour, pattern, period = LED[want]
                await band.set_led(colour, pattern=pattern, period=period)
            else:
                await band.led_off()
        except Exception as e:
            print("  [pixie] LED: %s" % e)

    async def flash_led(self, name, seconds, then="restore"):
        band = self.hub.band
        if not band or self.hub.status["mic"]:
            return
        colour, pattern, period = LED[name]
        try:
            await band.set_led(colour, pattern=pattern, period=period)
            await asyncio.sleep(seconds)
        except Exception as e:
            print("  [pixie] LED: %s" % e)
        await self.apply_led()


def signal_label(rssi):
    if rssi is None:
        return None
    if rssi > -60:
        return "Very close"
    if rssi > -75:
        return "Nearby"
    return "Far: edge of range"


def history_stats(history):
    week = [e for e in history if e.get("kind") == "help" and time.time() - e["created"] < 7 * 86400]
    labels = [e.get("outcome") for e in week if e.get("outcome")]
    return {"help_requests_7d": len(week), "accidental": labels.count("accidental"),
            "wanted_me": labels.count("wanted me"), "urgent": labels.count("urgent")}


# ==================================================================== AI assistant
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["urgency", "summary", "why", "suggested_action"],
    "properties": {
        "urgency": {"type": "string", "enum": ["normal", "urgent"]},
        "summary": {"type": "string", "description": "Notification line for the parent, max 12 words"},
        "why": {"type": "string", "description": "One short sentence: the evidence for the urgency"},
        "suggested_action": {"type": "string", "description": "One short sentence for the parent"},
    },
}
INSTRUCTIONS = (
    "You are Pixie's guardian assistant. A child wearing a screenless help band asked for their parent. "
    "From the facts (trigger, the child's short voice note, motion before the alert, past-week history), "
    "write what the parent needs at a glance. Mark urgency 'urgent' if there is any sign of injury, fear, "
    "being lost, a stranger, a fall, crying, or a repeated request. Never downplay: when unsure, choose "
    "'urgent'. Use the child's name. Be calm and concrete.")


SOURCE_NAMES = {"gemini": "Gemini", "ai": "AI assistant", "rules": "Rules"}


def assess_chain(facts, audio=b""):
    """Gemini (hears the audio: words AND tone) -> OpenAI (text) -> transparent rules."""
    if gemini.available():
        try:
            r = gemini.analyze(audio, gemini.ASSESS_PROMPT % json.dumps(facts), gemini.ASSESS_SCHEMA,
                               model=gemini.ASSESS_MODEL, timeout=40)
            r["source"] = "gemini"
            return r
        except Exception as e:
            print("  [pixie] Gemini assess failed: %s" % e)
    return ai_assess(facts)


def ai_assess(facts):
    """OpenAI if a key is set (kit's ai.py), else transparent keyword rules."""
    try:
        import ai                                            # kit helper; needs OPENAI_API_KEY
        found = ai.extract(json.dumps(facts), SCHEMA, INSTRUCTIONS)
        found["source"] = "ai"
        return found
    except Exception as e:                                   # no key / offline: fall back to rules
        result = rules_assess(facts)
        result["note"] = str(e)[:120]
        return result


def rules_assess(facts):
    text = facts["voice_note"].lower()
    hits = [w for w in URGENT_WORDS if w in text]
    repeated = any("again" in r or "fall" in r for r in facts["trigger"])
    urgent = bool(hits) or repeated
    said = facts["voice_note"] if facts["voice_note"] != "(silence)" else ""
    short = said if len(said) <= 60 else said[:60].rsplit(" ", 1)[0] + "…"
    summary = ('%s needs you: "%s"' % (facts["child"], short)) if said else "%s wants you" % facts["child"]
    why = ("heard: " + ", ".join(hits)) if hits else ("repeated request" if repeated else "single request, calm")
    return {"urgency": "urgent" if urgent else "normal", "summary": summary, "why": why,
            "suggested_action": "Go to %s now." % facts["child"] if urgent else "Let %s know you're coming." % facts["child"],
            "source": "rules"}
