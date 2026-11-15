"""
Whose voice is it? ElevenLabs Scribe tells Maya's voice apart from everyone else's.

Every VOICE_WINDOW seconds with sound, the buffered band audio is sent to Scribe (speech-to-text
with diarize=true and use_speaker_library=true), which returns each word with a speaker_id.
Each speaker's words become transcript segments tagged is_child:

  1. speaker library: a speaker_id that is a registered profile (not "speaker_N") is the child
     (CHILD_SPEAKER_ID in the env picks one profile if the workspace has several);
  2. voiceprint: each speaker's pitch + timbre is compared with the child's enrolled voiceprint
     (voiceprint.py); loudness is NOT used, since everyone near the band can be loud.

This runs in parallel with the Deepgram live path, which is untouched. The tags let child-only
features (things the child says, calling for a parent, quiet time) count only the child, while
safety features keep hearing everyone.

The key is read from ELEVENLABS_API_KEY (environment or .env.local, written by the ElevenLabs
CLI); it is never printed or put in code.
"""
import math
import os
import re
from pathlib import Path

import certfix  # noqa: F401  (HTTPS on this machine)

MODEL = "scribe_v2"                    # as specified; scribe_v3 is the newer batch model
VOICE_WINDOW = 15                      # seconds of audio per Scribe request
LOUDER_BY_DB = 4.0                     # the child must be this much louder than the next speaker
DEFAULT_CHILD_DB = -32.0               # dBFS a close-mic child voice usually reaches (before enrollment)
ROOT = Path(__file__).resolve().parent


from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env.local")       # ELEVENLABS_API_KEY, written by the ElevenLabs CLI (git-ignored)


def available():
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


_client = None


def client():
    global _client
    if _client is None:
        from elevenlabs import ElevenLabs
        _client = ElevenLabs()            # reads ELEVENLABS_API_KEY
    return _client


def _db(samples):
    """RMS level in dBFS of int16 samples."""
    if len(samples) == 0:
        return -96.0
    import numpy as np
    x = np.asarray(samples, dtype=np.float64)          # works for array('h') and numpy, no int16 overflow
    rms = math.sqrt(float(np.mean(x * x)))
    return 20 * math.log10(max(rms, 1.0) / 32768.0)


def _word_db(pcm, start, end, rate=16000):
    a, b = int(start * rate), int(end * rate)
    return _db(pcm[a:b]) if b > a else -96.0


def _span(pcm, start, end, rate=16000):
    return pcm[int(start * rate):int(end * rate)]


def identify(ogg_bytes, pcm_samples, profile=None):
    """Scribe + speaker tagging for one clip.
    pcm_samples: the same audio as int16 samples at 16 kHz; profile: the child's enrolled voiceprint.
    Returns {"segments": [{"speaker", "text", "start", "end", "db", "is_child", "sim"}], "method", "speakers"}."""
    import numpy as np
    import voiceprint as vp
    result = client().speech_to_text.convert(
        file=("clip.ogg", ogg_bytes, "audio/ogg"), model_id=MODEL, diarize=True, use_speaker_library=True,
        timestamps_granularity="word", tag_audio_events=False)
    words = [w for w in (result.words or []) if getattr(w, "type", "word") == "word" and (w.text or "").strip()]
    if not words:
        return {"segments": [], "method": "none", "speakers": 0}

    # consecutive words of one speaker = one segment
    segments = []
    for w in words:
        sp = w.speaker_id or "speaker_0"
        if segments and segments[-1]["speaker"] == sp and w.start - segments[-1]["end"] < 1.5:
            seg = segments[-1]
            seg["text"] += " " + w.text.strip()
            seg["end"] = w.end
            seg["dbs"].append(_word_db(pcm_samples, w.start, w.end))
        else:
            segments.append({"speaker": sp, "text": w.text.strip(), "start": w.start, "end": w.end,
                             "dbs": [_word_db(pcm_samples, w.start, w.end)]})

    wanted = os.environ.get("CHILD_SPEAKER_ID", "").strip()
    library = [s["speaker"] for s in segments if not re.fullmatch(r"speaker_\d+", s["speaker"])]
    sims = {}
    if library:                                          # 1. matched against the speaker library
        method = "library"
        child = {sp for sp in library if not wanted or sp == wanted}
    else:                                                # 2. voiceprint: pitch + timbre vs the enrolled child
        method = "voiceprint" if profile else "not enrolled"
        child = set()
        if profile:
            by_speaker = {}
            for s in segments:
                by_speaker.setdefault(s["speaker"], []).append(_span(pcm_samples, s["start"], s["end"]))
            best = None
            for sp, parts in by_speaker.items():
                vp_sp = vp.compute(np.concatenate([np.asarray(p) for p in parts if len(p)]) if parts else [])
                ok, sim, st = vp.is_match(vp_sp, profile)
                sims[sp] = (sim, st)
                if ok and (best is None or sim > sims[best][0]):
                    best = sp
            if best:
                child = {best}                          # one voice per clip can be the child: the closest match
    for s in segments:
        dbs = sorted(s.pop("dbs"))
        s["db"] = round(dbs[len(dbs) // 2], 1)          # median loudness, shown for information only
        s["is_child"] = s["speaker"] in child
        s["sim"] = sims.get(s["speaker"], (None, None))[0]
    return {"segments": segments, "method": method, "speakers": len({s["speaker"] for s in segments}),
            "child_speakers": sorted(child), "sims": sims}


FAST_MARGIN_DB = 5.0                   # instant tag: within this many dB of the child's enrolled level


def voiced_db(pcm_samples, rate=16000):
    """Loudness of the speech in a stretch of audio: the 75th-percentile 20 ms frame (pauses ignored)."""
    step = rate // 50
    frames = [_db(pcm_samples[i:i + step]) for i in range(0, len(pcm_samples) - step + 1, step)]
    if not frames:
        return None
    frames.sort()
    return frames[int(len(frames) * 0.75)]


def fast_tag(pcm_samples, profile=None):
    """Instant tag for a line that just ended: does the voice match the child's voiceprint?
    No network: ~1 s after the words instead of ~15 s. Scribe confirms or corrects it later.
    Returns (who, similarity): who is None when not enrolled or too little speech to tell."""
    import voiceprint as vp
    if not profile:
        return None, None
    ok, sim, _st = vp.is_match(vp.compute(pcm_samples), profile)
    if ok is None:
        return None, None
    return ("child" if ok else "other"), sim


def enroll(pcm_samples):
    """Enrollment from a clip of only the child talking: the voiceprint (+ loudness, for info)."""
    import voiceprint as vp
    return vp.compute(pcm_samples), voiced_db(pcm_samples)
