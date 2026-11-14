"""
Maya's day: a per-minute record of the day, and the daily summary built from it.

Every minute keeps: seconds still / walking / running, steps at the end of the minute, whether
Pixie was listening, and whether the child was talking WITH someone (Gemini heard the wearer
plus another voice, with words). The summary adds the day's alerts (history) and purchases
(wallet) and turns it all into stats + a picture (segments the page draws) + an AI paragraph.

Sample days ("typical", "rough") are generated example data for the demo.
"""
import json
import random
import time
from pathlib import Path

DAY_START, DAY_END = 7 * 60, 21 * 60          # 07:00 - 21:00, minutes after midnight
ALONE_MIN = 60                                  # an alone stretch worth showing


def minute_of(t):
    lt = time.localtime(t)
    return lt.tm_hour * 60 + lt.tm_min


class DayLog:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.date = None
        self.minutes = {}
        self._load(time.strftime("%Y-%m-%d"))
        self.last_save = 0.0

    def _load(self, date):
        self.date = date
        p = self.folder / ("%s.json" % date)
        self.minutes = {int(k): v for k, v in json.loads(p.read_text()).items()} if p.exists() else {}

    def save(self):
        (self.folder / ("%s.json" % self.date)).write_text(json.dumps(self.minutes))
        self.last_save = time.time()

    def tick(self, activity, steps, listening):
        """Called once a second while the band is connected."""
        now = time.time()
        if time.strftime("%Y-%m-%d") != self.date:
            self.save()
            self._load(time.strftime("%Y-%m-%d"))
        m = self.minutes.setdefault(minute_of(now), {"still": 0, "walk": 0, "run": 0, "steps": None,
                                                     "listened": False, "social": False})
        if activity in ("still", "walk", "run"):
            m[activity] += 1
        if steps is not None:
            m["steps"] = steps
        m["listened"] = m["listened"] or listening
        if now - self.last_save > 60:
            self.save()

    def mark_social(self):
        m = self.minutes.setdefault(minute_of(time.time()), {"still": 0, "walk": 0, "run": 0, "steps": None,
                                                             "listened": True, "social": False})
        m["social"] = m["listened"] = True


# ==================================================================== summary
def _segments(minutes, key):
    """Merge consecutive minutes with the same value of key(m) into [start, end, value]."""
    segs = []
    for mm in sorted(minutes):
        v = key(minutes[mm])
        if v is None:
            continue
        if segs and segs[-1][2] == v and segs[-1][1] == mm:
            segs[-1][1] = mm + 1
        else:
            segs.append([mm, mm + 1, v])
    return segs


def build(minutes, events, purchases, label, date, child):
    """Stats + drawing data for one day. minutes: {minute: bucket}; events: history entries;
    purchases: wallet transactions (approved / declined)."""
    def act(m):
        tot = m["still"] + m["walk"] + m["run"]
        if not tot:
            return None
        return "run" if m["run"] >= max(m["walk"], 5) else "walk" if m["walk"] >= 15 else "still"

    activity = _segments(minutes, act)
    social = _segments(minutes, lambda m: ("talk" if m["social"] else "quiet") if m["listened"] else None)
    alone = [s for s in social if s[2] == "quiet" and s[1] - s[0] >= ALONE_MIN]
    steps_vals = [m["steps"] for m in minutes.values() if m.get("steps") is not None]
    steps = (max(steps_vals) - min(steps_vals)) if len(steps_vals) > 1 else 0
    active_min = sum(1 for m in minutes.values() if act(m) in ("walk", "run"))
    talk_min = sum(1 for m in minutes.values() if m.get("social"))
    listened_min = sum(1 for m in minutes.values() if m.get("listened"))

    markers = []
    helps, answers, distress = 0, [], 0
    for e in events:
        k = e.get("kind")
        if k == "note" and not e.get("audio") and "hug" not in e["reasons"][0].lower():
            continue
        if k in ("help", "fall", "distress"):
            helps += k == "help"
            distress += k == "distress"
            if e.get("acked_at"):
                answers.append(e["acked_at"] - e["created"])
        icon = {"help": "🚨" if e.get("level", 1) >= 2 else "🙋", "fall": "🤸", "note": "💗" if "hug" in e["reasons"][0].lower() else "🗣"}.get(k)
        if k == "distress":
            icon = "⚠️" if e.get("concern_quotes") else "😢" if (e.get("signals") or {}).get("crying", 0) >= 0.6 else "😠"
        markers.append({"m": minute_of(e["created"]), "icon": icon, "text": e["reasons"][0]})
    spent = sum(p["amount"] for p in purchases if p["status"] == "approved")
    for p in purchases:
        markers.append({"m": minute_of(p["t"]), "icon": p["emoji"],
                        "text": "%s $%.2f%s" % (p["item"], p["amount"], "" if p["status"] == "approved" else " (declined)")})
    longest_alone = max([s[1] - s[0] for s in social if s[2] == "quiet"] or [0])
    return {
        "type": "day", "label": label, "date": date, "child": child,
        "range": [DAY_START, DAY_END],
        "stats": {"steps": steps, "active_min": active_min, "talk_min": talk_min, "listened_min": listened_min,
                  "longest_alone": longest_alone, "alone_stretches": len(alone), "help": helps, "distress": distress,
                  "avg_answer": round(sum(answers) / len(answers)) if answers else None,
                  "spent": round(spent, 2), "purchases": len([p for p in purchases if p["status"] == "approved"])},
        "activity": activity, "social": social, "alone": alone, "markers": sorted(markers, key=lambda x: x["m"]),
    }


# ==================================================================== sample days (demo data)
def _fill(minutes, start, end, state, steps_per_min, social=0.0, rnd=None):
    """social: share of minutes in this block where the child talks with someone (0-1)."""
    for mm in range(start, end):
        b = minutes.setdefault(mm, {"still": 0, "walk": 0, "run": 0, "steps": None, "listened": True, "social": False})
        b[state] = 60
        b["social"] = rnd.random() < social if rnd else social >= 1
    return int(steps_per_min * 0.45 * (end - start))


def sample_day(kind, child):
    """A generated example day: 'typical' or 'rough'."""
    rnd = random.Random(7 if kind == "typical" else 13)
    day = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))   # local midnight
    T = lambda h, m=0: h * 60 + m                         # noqa: E731
    at = lambda mm: day + mm * 60                          # noqa: E731
    minutes = {}
    plan = {
        "typical": [(T(7), T(7, 40), "still", 5, True), (T(7, 40), T(8, 10), "walk", 95, True),
                    (T(8, 10), T(10, 15), "still", 8, True), (T(10, 15), T(10, 45), "run", 150, True),
                    (T(10, 45), T(12), "still", 6, True), (T(12), T(12, 40), "walk", 60, True),
                    (T(12, 40), T(15), "still", 7, True), (T(15), T(15, 30), "walk", 100, True),
                    (T(15, 30), T(16, 30), "run", 140, True), (T(16, 30), T(18), "still", 10, True),
                    (T(18), T(19), "walk", 40, True), (T(19), T(20, 30), "still", 4, True)],
        "rough": [(T(7), T(7, 50), "still", 3, False), (T(7, 50), T(8, 15), "walk", 90, False),
                  (T(8, 15), T(11, 5), "still", 4, False), (T(11, 5), T(11, 25), "walk", 70, True),
                  (T(11, 25), T(12, 30), "still", 5, False), (T(12, 30), T(12, 50), "run", 160, False),
                  (T(12, 50), T(15, 10), "still", 3, False), (T(15, 10), T(15, 35), "walk", 85, True),
                  (T(15, 35), T(18, 20), "still", 5, False), (T(18, 20), T(19, 30), "still", 4, True),
                  (T(19, 30), T(20, 30), "still", 2, False)],
    }[kind]
    total = 1000 if kind == "typical" else 600
    for s, e, state, spm, social in plan:
        share = (0.4 if kind == "typical" else 0.5) if social else 0.0
        total += _fill(minutes, s, e, state, spm, share, rnd)
        minutes[e - 1]["steps"] = total
    minutes[min(minutes)]["steps"] = 1000 if kind == "typical" else 600
    ev = lambda mm, kind_, reason, **k: dict({"kind": kind_, "created": at(mm), "reasons": [reason]}, **k)  # noqa: E731
    if kind == "typical":
        events = [ev(T(10, 30), "help", "%s double-tapped the band" % child, level=1, acked_at=at(T(10, 30)) + 14,
                     outcome="wanted me"),
                  ev(T(15, 50), "fall", "Possible fall detected", level=1, outcome="ok"),
                  ev(T(13, 5), "note", "Mom sent %s a hug" % child)]
        purchases = [{"t": at(T(12, 20)), "item": "Apple juice", "emoji": "🧃", "amount": 2.0, "status": "approved"},
                     {"t": at(T(16, 40)), "item": "Ice cream", "emoji": "🍦", "amount": 3.5, "status": "approved"}]
    else:
        events = [ev(T(9, 40), "distress", "Pixie heard %s crying" % child, level=1, signals={"crying": 0.85},
                     acked_at=at(T(9, 40)) + 95, outcome="urgent"),
                  ev(T(12, 45), "help", "%s double-tapped the band" % child, level=2, acked_at=at(T(12, 45)) + 41,
                     outcome="urgent"),
                  ev(T(14, 20), "distress", "Pixie heard an angry adult voice near %s" % child, level=2,
                     signals={"adult_anger": 0.8}, acked_at=at(T(14, 20)) + 60, outcome="wanted me"),
                  ev(T(17, 10), "help", "%s double-tapped the band" % child, level=1, acked_at=at(T(17, 10)) + 22,
                     outcome="wanted me")]
        purchases = [{"t": at(T(11, 15)), "item": "Candy bar", "emoji": "🍫", "amount": 1.5, "status": "approved"},
                     {"t": at(T(15, 20)), "item": "Game card", "emoji": "🎮", "amount": 15.0, "status": "declined"}]
    label = "A typical day (example)" if kind == "typical" else "A rough day (example)"
    return build(minutes, events, purchases, label, time.strftime("%A"), child)


# ==================================================================== AI paragraph
DAY_SCHEMA = {
    "type": "OBJECT",
    "properties": {"headline": {"type": "STRING"}, "summary": {"type": "STRING"},
                   "highlights": {"type": "ARRAY", "items": {"type": "STRING"}},
                   "watch_for": {"type": "STRING"}},
    "required": ["headline", "summary", "highlights", "watch_for"],
}
DAY_PROMPT = (
    "You write the end-of-day note in Pixie, a screenless help band for a young child. Using the day's "
    "facts below, write for the parent: a warm headline (max 8 words), a 2-3 sentence summary of how the "
    "day went, 3 short highlights (each starting with an emoji), and one gentle thing to watch for "
    "tomorrow (or 'Nothing in particular'). Be factual: only use the facts given. Be honest: a hard day "
    "(distress alerts, urgent requests, little movement, long stretches alone) must read as a hard day, "
    "said kindly; never dress it up as great. For reference a typical child walks 8,000-12,000 steps. "
    "Long stretches without talking to anyone matter for some children (for example autistic children): "
    "name them plainly and kindly as time alone, not as 'peaceful', and never alarmingly. Facts: %s")


def ai_note(day):
    import gemini
    facts = {"child": day["child"], "stats": day["stats"],
             "alone_stretches": [{"from": "%02d:%02d" % divmod(s, 60), "to": "%02d:%02d" % divmod(e, 60)} for s, e, _ in day["alone"]],
             "moments": ["%02d:%02d %s" % (*divmod(m["m"], 60), m["text"]) for m in day["markers"]]}
    return gemini.analyze(b"", DAY_PROMPT % json.dumps(facts), DAY_SCHEMA, model=gemini.ASSESS_MODEL, timeout=40)
