"""
Patterns over weeks and months, compared with the child's OWN baseline.

Each week has a few behaviour numbers (steps, time talking with others, long alone stretches,
crying, help requests) and counts of things the child said, grouped by theme (tummy aches,
headaches, tiredness, loneliness, worry). The baseline is the child's average and spread over
the earlier weeks (all but the most recent BASELINE_SKIP); a metric is flagged when this week is
clearly outside that range. Gemini turns the flags into plain-language patterns with gentle,
non-diagnostic next steps.

The demo uses generated example data (26 weeks). count_mentions() is how real transcripts are
counted as they build up.
"""
import json
import random
import re
import statistics
import time

BASELINE_SKIP = 4          # the most recent weeks are compared, not part of the baseline

METRICS = [  # key, label, icon, unit, "higher is" (good / bad)
    ("steps", "Steps a day", "👣", "", "good"),
    ("talk_min", "Talking with others", "💬", "min/day", "good"),
    ("alone_long", "Alone 1 h+ stretches", "🫥", "/week", "bad"),
    ("crying", "Crying heard", "😢", "/week", "bad"),
    ("help", "Help requests", "🙋", "/week", "bad"),
]
MENTIONS = [  # key, label, icon, kind, pattern
    ("tummy", '"My tummy hurts"', "🤢", "health", r"\b(tummy|stomach|belly)\b.{0,15}\b(hurts?|ache|sore)|\bfeel sick\b"),
    ("head", '"My head hurts"', "🤕", "health", r"\bhead\b.{0,10}\b(hurts?|ache)|\bheadache\b"),
    ("tired", '"I\'m tired"', "😴", "health", r"\b(i'm|i am|so) tired\b"),
    ("lonely", '"Nobody plays with me"', "🧍", "isolation", r"\bnobody (wants to )?plays?\b|\bno friends\b|\bplay alone\b"),
    ("worry", '"I\'m scared / don\'t want to go"', "😟", "anxiety", r"\b(i'm|i am) (scared|worried)\b|\bdon'?t want to go\b"),
]


def count_mentions(lines):
    """Theme counts for transcript lines (real data path)."""
    out = {k: 0 for k, *_ in MENTIONS}
    for l in lines:
        for k, _l, _i, _kind, rx in MENTIONS:
            if re.search(rx, l["text"], re.I):
                out[k] += 1
    return out


# ==================================================================== example data
def example_weeks(n=26):
    """26 weeks for a child whose last 3 weeks drift: tummy aches, worry, less talking, more alone time."""
    rnd = random.Random(2026)
    weeks = []
    now = time.time()
    for i in range(n):
        drift = max(0, i - (n - 4))                       # 0 ... 3 over the last three weeks
        w = {"start": now - (n - 1 - i) * 7 * 86400,
             "steps": int(rnd.gauss(10400, 550) - drift * 220),
             "talk_min": int(rnd.gauss(205, 18) - drift * 28),
             "alone_long": max(0, int(round(rnd.gauss(2, 0.9) + drift * 1.4))),
             "crying": max(0, int(round(rnd.gauss(1, 0.7) + drift * 1.0))),
             "help": max(0, int(round(rnd.gauss(3, 1.0) + drift * 0.3))),
             "mentions": {"tummy": max(0, int(round(rnd.gauss(2, 0.9) + drift * 3.4))),
                          "head": max(0, int(round(rnd.gauss(1, 0.7)))),
                          "tired": max(0, int(round(rnd.gauss(3, 1.1)))),
                          "lonely": max(0, int(round(rnd.gauss(0.4, 0.5) + drift * 1.1))),
                          "worry": max(0, int(round(rnd.gauss(0.8, 0.6) + drift * 1.3)))}}
        weeks.append(w)
    return weeks


def _months(weeks):
    """Group weeks into 4-week 'months' (sums for counts, averages for per-day numbers)."""
    out = []
    for i in range(len(weeks) % 4, len(weeks), 4):
        chunk = weeks[i:i + 4]
        m = {"start": chunk[0]["start"], "mentions": {}}
        for k in ("steps", "talk_min"):
            m[k] = int(sum(w[k] for w in chunk) / len(chunk))
        for k in ("alone_long", "crying", "help"):
            m[k] = sum(w[k] for w in chunk)
        for k, *_ in MENTIONS:
            m["mentions"][k] = sum(w["mentions"][k] for w in chunk)
        out.append(m)
    return out


def analyse(periods, unit):
    """Series + baseline + flags for each metric and mention theme."""
    skip = BASELINE_SKIP if unit == "week" else 1
    base_part = periods[:-skip] if len(periods) > skip + 2 else periods[:-1]

    def stats(values_all, base_values, good_dir):
        mean = statistics.mean(base_values)
        sd = statistics.pstdev(base_values) or max(1.0, mean * 0.1)
        now_v = values_all[-1]
        z = (now_v - mean) / sd
        worse = (z < 0) if good_dir == "good" else (z > 0)
        flag = abs(z) >= 2 and worse
        return {"series": values_all, "now": now_v, "baseline": round(mean, 1), "low": round(max(0, mean - sd), 1),
                "high": round(mean + sd, 1), "change_pct": round((now_v - mean) / mean * 100) if mean else None,
                "z": round(z, 1), "flag": flag, "better": abs(z) >= 2 and not worse and good_dir == "good"}

    metrics = []
    for key, label, icon, unit_l, good in METRICS:
        s = stats([p[key] for p in periods], [p[key] for p in base_part], good)
        s.update(key=key, label=label, icon=icon, unit=unit_l)
        metrics.append(s)
    mentions = []
    for key, label, icon, kind, _ in MENTIONS:
        s = stats([p["mentions"][key] for p in periods], [p["mentions"][key] for p in base_part], "bad")
        s.update(key=key, label=label, icon=icon, kind=kind)
        mentions.append(s)
    return {"unit": unit, "count": len(periods), "baseline_periods": len(base_part),
            "labels": [time.strftime("%b %d", time.localtime(p["start"])) for p in periods],
            "metrics": metrics, "mentions": mentions}


def build(view, child):
    weeks = example_weeks()
    data = analyse(weeks[-12:] if view == "weeks" else _months(weeks), "week" if view == "weeks" else "month")
    if view == "weeks":                                   # baseline from the full history, shown over 12 weeks
        full = analyse(weeks, "week")
        for part in ("metrics", "mentions"):
            for shown, f in zip(data[part], full[part]):
                shown.update({k: f[k] for k in ("baseline", "low", "high", "change_pct", "z", "flag", "better")})
        data["baseline_periods"] = full["baseline_periods"]
    data.update(type="trends", view=view, child=child, example=True)
    return data


# ==================================================================== AI patterns
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "patterns": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "title": {"type": "STRING"}, "detail": {"type": "STRING"},
            "kind": {"type": "STRING", "enum": ["health", "anxiety", "isolation", "activity", "positive"]},
            "suggest": {"type": "STRING"}},
            "required": ["title", "detail", "kind", "suggest"]}},
    },
    "required": ["summary", "patterns"],
}
PROMPT = (
    "You help a parent read long-term patterns from Pixie, a wristband for their young child %s. Compare "
    "the most recent %s with the child's OWN baseline (their usual average and range). Data: %s\n"
    "Write a 2-sentence summary, then up to 4 patterns, most important first. Each pattern: a short title, "
    "the evidence in numbers vs baseline (e.g. 'said \"my tummy hurts\" 12 times this week, usually about "
    "2'), the kind, and one gentle, practical next step (e.g. 'mention it to your pediatrician', 'ask the "
    "teacher how breaks and lunch are going', 'plan a playdate'). Connect related signals when the data "
    "supports it (for example tummy aches together with not wanting to go to school can be a sign of "
    "worry). Never diagnose and never alarm; do not invent numbers. Include one positive pattern if there "
    "is one.")


def ai_patterns(data):
    import gemini
    compact = {"unit": data["unit"],
               "metrics": [{k: m[k] for k in ("label", "now", "baseline", "low", "high", "change_pct", "flag")}
                           for m in data["metrics"]],
               "said": [{k: m[k] for k in ("label", "kind", "now", "baseline", "flag")} for m in data["mentions"]],
               "recent_series": {m["label"]: m["series"][-6:] for m in data["metrics"] + data["mentions"]}}
    return gemini.analyze(b"", PROMPT % (data["child"], data["unit"], json.dumps(compact)), SCHEMA,
                          model=gemini.ASSESS_MODEL, timeout=40)
