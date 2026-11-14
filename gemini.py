"""
Gemini audio analysis for Pixie: send a short Ogg Opus clip + instructions, get JSON back.

Keys come from .env (never from code): GEMINI_API_KEY first, GEMINI_WORKSHOP_API_KEY as a
fallback when the first is rate-limited (429) or refused. A 503 (model overloaded) retries
once on FALLBACK_MODEL. MAX_PER_HOUR caps requests (hackathon fair-use rule).
All calls are blocking: run them in a thread (loop.run_in_executor).
"""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import certfix  # noqa: F401  (HTTPS on this machine)

LISTEN_MODEL = "gemini-3.5-flash-lite"      # ~1.5 s per 5 s window
ASSESS_MODEL = "gemini-3.8-flash"           # ~4 s, smarter: help-request voice notes
FALLBACK_MODEL = "gemini-flash-lite-latest"
KEY_NAMES = ("GEMINI_API_KEY", "GEMINI_WORKSHOP_API_KEY")
MAX_PER_HOUR = 400
URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
ENV_FILE = Path(__file__).resolve().parent / ".env"

_lock = threading.Lock()
_sent = []                                   # request times, for the hourly cap


class GeminiError(Exception):
    pass


def keys():
    found = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.strip().partition("=")
            if name.strip() in KEY_NAMES and value.strip():
                found[name.strip()] = value.strip().strip("'\"")
    for name in KEY_NAMES:
        if os.environ.get(name):
            found[name] = os.environ[name].strip()
    return [found[n] for n in KEY_NAMES if n in found]


def available():
    return bool(keys())


def requests_last_hour():
    now = time.time()
    with _lock:
        while _sent and now - _sent[0] > 3600:
            _sent.pop(0)
        return len(_sent)


def analyze(audio: bytes, prompt: str, schema: dict, model: str = LISTEN_MODEL, timeout: float = 30,
            mime: str = "audio/ogg") -> dict:
    """Audio + prompt -> dict following `schema` (Gemini responseSchema format)."""
    all_keys = keys()
    if not all_keys:
        raise GeminiError("no Gemini key: add GEMINI_API_KEY to .env")
    if requests_last_hour() >= MAX_PER_HOUR:
        raise GeminiError("hourly request cap reached (%d)" % MAX_PER_HOUR)
    parts = [{"text": prompt}]
    if audio:
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}})
    body = json.dumps({"contents": [{"parts": parts}],
                       "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                                            "temperature": 0.2}}).encode()
    last = None
    for m in (model, FALLBACK_MODEL):
        for key in all_keys:
            with _lock:
                _sent.append(time.time())
            req = urllib.request.Request(URL % m, data=body,
                                         headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            try:
                out = json.load(urllib.request.urlopen(req, timeout=timeout))
                text = out["candidates"][0]["content"]["parts"][0]["text"]
                result = json.loads(text)
                result["_model"] = m
                return result
            except urllib.error.HTTPError as e:
                last = "HTTP %d from %s" % (e.code, m)
                if e.code in (429, 401, 403):
                    continue                 # try the other key
                if e.code in (500, 503):
                    break                    # model overloaded: try the fallback model
                raise GeminiError(last)
            except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
                last = "%s: %s" % (type(e).__name__, e)
                break
    raise GeminiError(last or "Gemini failed")


# ==================================================================== Pixie prompts
LISTEN_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "crying": {"type": "NUMBER"},
        "screaming": {"type": "NUMBER"},
        "adult_anger": {"type": "NUMBER"},
        "child_distress": {"type": "NUMBER"},
        "child_calling": {"type": "NUMBER"},
        "adult_concerning": {"type": "NUMBER"},
        "concern": {"type": "STRING"},
        "concern_quote": {"type": "STRING"},
        "children": {"type": "INTEGER"},
        "adults": {"type": "INTEGER"},
        "transcript": {"type": "STRING"},
        "evidence": {"type": "STRING"},
    },
    "required": ["crying", "screaming", "adult_anger", "child_distress", "child_calling", "adult_concerning", "concern",
                 "concern_quote", "children", "adults", "transcript", "evidence"],
}
LISTEN_PROMPT = (
    "This is the newest 5 seconds of audio from a microphone on a young child's wristband (the child is the "
    "wearer). Score from 0 to 1 how clearly you hear: crying or sobbing (any age, mostly the child), screaming "
    "or shrieking in fear or pain (NOT happy play screams or cheering), an adult speaking angrily, harshly or "
    "aggressively (a hostile, raised or threatening tone; a soft or coaxing voice is NOT anger), and overall "
    "distress of the child.\n"
    "Score child_calling: how clearly the CHILD (not an adult) calls out for a parent or caregiver or asks "
    "for help, e.g. 'Mommy!', 'Dad, where are you?', 'Help!', 'Come here, Mom'. Talking ABOUT mom in a "
    "normal sentence is not calling.\n"
    "Also score adult_concerning: how strongly an adult's words or manner toward the child match known "
    "luring or grooming patterns: asking the child to keep a secret from parents, offering gifts, sweets, "
    "pets or games to get the child to go somewhere, asking the child to come with them or get in a car, "
    "asking whether the child is alone or where they live, saying the parent sent them, unusual flattery or "
    "talk about the child's body, or pressuring the child after a no. Ordinary adult care (a parent, teacher "
    "or coach giving normal instructions, offering help to a lost child in the open) is NOT concerning. "
    "Describe the pattern in `concern` in a few plain words a parent understands, e.g. 'offered puppies to "
    "get the child into a van, asked them to keep it secret' (empty if none). In `concern_quote` put the "
    "adult's exact worrying words, word for word, from the new audio (empty if none). Judge the new audio "
    "together with the recent "
    "conversation below, since these patterns build over time.\n"
    "Count the distinct child and adult voices you hear (0 if none). Background crowd noise, laughter and "
    "normal conversation are not distress. Give a short transcript of clear words in the new audio (empty "
    "if none) and one short sentence of evidence.\n"
    "Recent conversation (oldest first, may be empty):\n%s")

ASSESS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "urgency": {"type": "STRING", "enum": ["normal", "urgent"]},
        "summary": {"type": "STRING"},
        "why": {"type": "STRING"},
        "suggested_action": {"type": "STRING"},
        "tone": {"type": "STRING"},
        "children": {"type": "INTEGER"},
        "adults": {"type": "INTEGER"},
        "transcript": {"type": "STRING"},
    },
    "required": ["urgency", "summary", "why", "suggested_action", "tone", "children", "adults", "transcript"],
}
ASSESS_PROMPT = (
    "You are Pixie's guardian assistant. A child wearing a screenless help band asked for their parent; "
    "the audio is the few seconds recorded right after. Facts from the band: %s. "
    "Listen to the words AND the tone (crying, fear, pain, an angry adult nearby). Write for the parent: "
    "a notification line of at most 12 words using the child's name, the evidence (why), one suggested "
    "action, the child's tone in 1-3 words, how many child and adult voices you hear, and the transcript. "
    "Urgency 'urgent' if there is any sign of injury, fear, crying, being lost, a stranger, an angry adult, "
    "a fall, or a repeated request. Never downplay: when unsure, choose 'urgent'.")
