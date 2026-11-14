"""
Pixie Card (DEMO ONLY): tap-to-pay pocket money on the band.

Nothing here touches real money or a real card network. The "card" is a label, the shop is a
web page (/shop), and the "tap" is the band's own single-tap gesture while the shop's reader is
waiting (the band has no NFC). Double-tap stays reserved for asking for help.

  parent: create card, daily budget, per-purchase limit, allowed categories, freeze
  shop:   pick an item -> reader waits REARM_SECONDS for a band tap -> approve / decline / ask parent
  over a limit -> the parent gets Approve / Decline on the mom view; the shop waits for the answer
"""
import asyncio
import json
import time
from pathlib import Path

ITEMS = [
    {"id": "lolly", "name": "Lollipop", "emoji": "ðŸ­", "price": 0.75, "cat": "snacks"},
    {"id": "candy", "name": "Candy bar", "emoji": "ðŸ«", "price": 1.50, "cat": "snacks"},
    {"id": "juice", "name": "Apple juice", "emoji": "ðŸ§ƒ", "price": 2.00, "cat": "drinks"},
    {"id": "icecream", "name": "Ice cream", "emoji": "ðŸ¦", "price": 3.50, "cat": "snacks"},
    {"id": "car", "name": "Toy car", "emoji": "ðŸš—", "price": 8.00, "cat": "toys"},
    {"id": "game", "name": "Game card", "emoji": "ðŸŽ®", "price": 15.00, "cat": "games"},
]
CATEGORIES = {"snacks": "Snacks & sweets", "drinks": "Drinks", "toys": "Toys", "games": "Games & apps"}
REARM_SECONDS = 20        # how long the reader waits for a tap
ASK_SECONDS = 120         # how long a parent request stays open
DEFAULTS = {"card": None, "daily": 10.0, "per_purchase": 5.0, "frozen": False,
            "categories": {"snacks": True, "drinks": True, "toys": True, "games": False}, "tx": []}


class Wallet:
    def __init__(self, pixie, path: Path):
        self.pixie = pixie
        self.path = path
        self.data = dict(DEFAULTS, **(json.loads(path.read_text()) if path.exists() else {}))
        self.pending = None               # the purchase at the reader right now

    # ------------------------------------------------------------ state
    def save(self):
        self.path.write_text(json.dumps(self.data, indent=1))

    def spent_today(self):
        today = time.strftime("%Y-%m-%d")
        return round(sum(t["amount"] for t in self.data["tx"]
                         if t["status"] == "approved" and time.strftime("%Y-%m-%d", time.localtime(t["t"])) == today), 2)

    def snapshot(self):
        d = self.data
        p = self.pending
        if p and p["state"] == "waiting_tap" and time.time() > p["expires"]:
            p["state"], p["message"] = "expired", "No tap. Try again!"
        return {"card": d["card"], "daily": d["daily"], "per_purchase": d["per_purchase"], "frozen": d["frozen"],
                "categories": d["categories"], "category_names": CATEGORIES, "spent_today": self.spent_today(),
                "left_today": round(max(0.0, d["daily"] - self.spent_today()), 2), "items": ITEMS,
                "recent": d["tx"][-8:][::-1], "pending": p}

    # ------------------------------------------------------------ commands (mom view + shop)
    async def command(self, cmd):
        act = cmd.get("action")
        d = self.data
        if act == "create_card":
            d["card"] = {"name": self.pixie.child, "label": "Pixie Card", "last4": "DEMO", "created": time.time()}
            self.pixie.log_line("%s created %s's Pixie Card (demo)" % (self.pixie.guardian, self.pixie.child))
        elif act == "set":
            for k in ("daily", "per_purchase"):
                if k in cmd:
                    d[k] = round(max(0.0, min(500.0, float(cmd[k]))), 2)
            if isinstance(cmd.get("categories"), dict):
                d["categories"].update({k: bool(v) for k, v in cmd["categories"].items() if k in CATEGORIES})
            if "frozen" in cmd:
                d["frozen"] = bool(cmd["frozen"])
        elif act == "arm":                                   # shop: item chosen, reader waits for a tap
            item = next((i for i in ITEMS if i["id"] == cmd.get("item")), None)
            if item:
                self.pending = {"id": "%d" % (time.time() * 1000), "item": item, "state": "waiting_tap",
                                "expires": time.time() + REARM_SECONDS, "message": "Tap your Pixie band on the reader"}
        elif act == "tap":                                   # shop's demo button = a band tap
            await self.on_tap()
        elif act == "cancel":
            self.pending = None
        elif act == "decide":                                # parent answers an over-limit request
            p = self.pending
            if p and p["state"] == "asking" and p["id"] == cmd.get("id"):
                if cmd.get("approve"):
                    await self.finish(p, "approved", "%s said yes!" % self.pixie.guardian, by_parent=True)
                else:
                    await self.finish(p, "declined", "%s said not this time." % self.pixie.guardian, by_parent=True)
        self.save()

    async def on_tap(self):
        p = self.pending
        if not p or p["state"] != "waiting_tap" or time.time() > p["expires"]:
            return
        d, item = self.data, p["item"]
        if not d["card"]:
            return await self.finish(p, "declined", "No Pixie Card yet. Ask a grown-up to set it up.")
        if d["frozen"]:
            return await self.finish(p, "declined", "Your card is paused right now.")
        if not d["categories"].get(item["cat"], False):
            return await self.ask(p, "%s aren't allowed yet" % CATEGORIES[item["cat"]].lower())
        if item["price"] > d["per_purchase"]:
            return await self.ask(p, "over the $%.2f limit per purchase" % d["per_purchase"])
        if self.spent_today() + item["price"] > d["daily"]:
            return await self.ask(p, "over today's $%.2f budget" % d["daily"])
        await self.finish(p, "approved", "Paid! Enjoy your %s." % item["name"].lower())

    async def ask(self, p, why):
        p.update(state="asking", why=why, asked=time.time(),
                 message="Asking %sâ€¦ (%s)" % (self.pixie.guardian, why))
        self.pixie.log_line("%s asked to buy %s for $%.2f (%s)" % (self.pixie.child, p["item"]["name"],
                                                                  p["item"]["price"], why))
        self.pixie.publish()                                 # tell the pages first, then the light
        asyncio.ensure_future(self.pixie.show_light("asking", 2))

    async def finish(self, p, status, message, by_parent=False):
        p.update(state=status, message=message)
        tx = {"id": p["id"], "t": time.time(), "item": p["item"]["name"], "emoji": p["item"]["emoji"],
              "amount": p["item"]["price"], "status": status, "note": p.get("why", ""),
              "by_parent": by_parent}
        self.data["tx"].append(tx)
        self.data["tx"] = self.data["tx"][-200:]
        self.save()
        self.pixie.publish()
        asyncio.ensure_future(self.pixie.show_light("paid" if status == "approved" else "declined", 1.5))
