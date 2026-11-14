"""End-to-end: pretend band plays scenes.ogg, listening mode on; log every alert with its time."""
import asyncio
import json
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import certfix  # noqa: F401,E402
import aiohttp  # noqa: E402

URL = "http://127.0.0.1:8766/ws"
SCENES = [("calm", 0, 8.6), ("teacher", 12.6, 21.9), ("angry_adult", 25.9, 38.1),
          ("scared_child", 42.1, 58.8), ("luring", 62.8, 87.3)]
snap, alerts, seen = {}, [], set()


def scene_at(t):
    for name, a, b in SCENES:
        if a - 1 <= t <= b + 6:          # a window can end a few seconds after the scene
            return name
    return "gap"


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(URL) as ws:
            async def reader():
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        m = json.loads(msg.data)
                        if m["type"] == "pixie":
                            snap.update(m)
            task = asyncio.ensure_future(reader())
            await asyncio.sleep(2)
            await ws.send_str(json.dumps({"cmd": "listen", "on": True}))
            t0 = time.time()                     # the pretend band starts its sound when the mic turns on
            while time.time() - t0 < 96:
                await asyncio.sleep(1)
                a = snap.get("active")
                if a and a["id"] not in seen:
                    seen.add(a["id"])
                    t = time.time() - t0
                    alerts.append({"t": round(t, 1), "scene": scene_at(t - 2.5), "id": a["id"]})
                    asyncio.ensure_future(resolve_later(ws, a["id"]))
            await ws.send_str(json.dumps({"cmd": "listen", "on": False}))
            await asyncio.sleep(2)
            task.cancel()
    hist = {e["id"]: e for e in snap.get("history", [])}
    print("\n=== ALERTS")
    for al in alerts:
        e = hist.get(al["id"], {})
        print("t=%5.1fs during %-12s level %s | %s" % (al["t"], al["scene"], e.get("level"), " / ".join(e.get("reasons", []))))
        if e.get("concern"):
            print("     concern:", e["concern"])
        if e.get("ai"):
            print("     %s: %s | %s" % (e["ai"].get("source"), e["ai"].get("summary"), e["ai"].get("why", "")[:120]))
    print("\n=== NOTES")
    for e in snap.get("history", [])[::-1]:
        if e["kind"] == "note" and "Raised adult" in e["reasons"][0]:
            print("  ", e["reasons"][0][:150], "| clip:", e.get("audio"))


async def resolve_later(ws, eid):
    await asyncio.sleep(8)                       # long enough for the Gemini assessment
    a = snap.get("active")
    if a and a["id"] == eid:
        await ws.send_str(json.dumps({"cmd": "resolve", "by": "Test", "outcome": "urgent"}))

asyncio.run(main())
