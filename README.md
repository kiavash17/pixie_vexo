# pixie_vexo

Hello world for the Vexo Open band (VexoHacks). It connects to band **06** (`Vexo-HACK-06`)
over Bluetooth and reads every sensor plus the microphone.

- **Phase 1 (10 s):** LED green; live accelerometer + gyroscope, taps/gestures, steps,
  battery, chip temperature, Bluetooth signal strength.
- **Phase 2 (10 s):** microphone on (the band's light is solid blue), loudness meter, voice
  saved to `hello.ogg`, and a live transcript through Deepgram when a key is set.

## Pixie guardian app (`/mom`)

`python server.py`, then open `http://localhost:8765/mom` (the parent's phone view).

- **Help request:** the child double-taps the band, Mom is alerted at once, and the mic opens
  for 8 s (voice note + transcript). A second double-tap makes it urgent.
- **Acknowledgement on the wrist:** amber = waiting, red = urgent, green = "I'm coming".
- **Escalation:** no answer in 30 s → louder + second guardian; then a (simulated) call.
- **Listening mode (Gemini):** 5 s windows with sound go to Gemini, which scores crying,
  screaming, adult anger and **concerning adult behaviour** (luring/grooming patterns judged
  with the last 2 min of conversation), and counts child/adult voices. A signal must persist
  (2 of 3 windows, or one ≥ 0.85). Crying → alert; screaming / angry or concerning adult →
  urgent alert. Clips: 30 s (+20 s after), 60 s for concerning adults; any adult anger ≥ 0.4
  is logged with a 15 s clip. Audio otherwise stays in a 60 s RAM buffer.
- **Assessment:** Gemini hears the clip (words and tone) and writes summary, tone, voices,
  suggested action; it can raise urgency, never lower it. Fallback: OpenAI, then rules.
- **Worrying adult alerts** get their own high-alarm card that shows at once what was detected
  ("offered puppies to get the child into a van…") and the adult's exact words.
- **Fall check, hug, find band, event log with outcome labels, offline/low-battery banners.**
- **Guardian UX:** action-first alert card, one consistent message, plain words, band status in
  the header, first-run sound prompt, settings sheet (⚙), demo buttons only with `/mom?demo=1`.

### Pixie Card: tap to pay (demo only, no real money)

Mom creates a Pixie Card and sets a daily budget, a per-purchase limit and allowed categories
(Settings ⚙). At the pretend shop `http://localhost:8765/shop` the child picks a treat and
**taps the band once** (the band has no NFC; its tap gesture stands in for the reader). Within the
rules it's paid (band flashes green); over a limit or in a blocked category Mom gets
**Approve / Not this time** on the mom view and the shop waits for her answer.

Keys in `.env` (never committed): `DEEPGRAM_API_KEY`, `GEMINI_API_KEY`
(optional fallback `GEMINI_WORKSHOP_API_KEY`).

### Testing without a band

```
python tests/make_test_audio.py testaudio             # Gemini TTS: calm, teacher, angry adult, scared child, luring
python tests/to_band_ogg.py testaudio/scenes.ogg 4 testaudio/calm.wav testaudio/teacher.wav testaudio/angry_adult.wav testaudio/scared_child.wav testaudio/luring.wav
python server.py --sim --port 8766 --sim-audio testaudio/scenes.ogg
python tests/test_scenes.py                           # turns on listening mode, prints every alert
```

Result on 2026-11-14: no alerts for the calm and teacher scenes; urgent alerts for the angry
adult (0.90), crying (0.80–0.90) and the luring adult (0.90–0.95, "asked the child to keep a
secret and go with them").

## Control room (`server.py`)

A live diagnostic page for the band: live transcript, accelerometer / gyroscope / mic
loudness / chip temperature / signal charts, gesture log, live audio playback, and every
mic session saved to `recordings/*.ogg`. The terminal prints one parsed line per second.

```
python server.py          # then open http://localhost:8765, double-tap the band, press Connect
python server.py --sim    # pretend band
```

The server holds the band (Bluetooth) and the Deepgram key; the page only gets data over a
WebSocket (works through `https` tunnels too). Sentences are split on Deepgram's
`UtteranceEnd` as well as silence, so the transcript works in a noisy room.

Needs `aiohttp` as well: `python -m pip install aiohttp`.

## Setup

```
git clone https://github.com/kiavash17/pixie_vexo.git
cd pixie_vexo
git clone https://github.com/VexoAI-Org/vexo-open-kit.git
python -m pip install bleak av certifi
```

Python 3.9 or newer. For transcripts, create `.env` in this folder (it is git-ignored):

```
DEEPGRAM_API_KEY=your-key
```

## Run

Double-tap the band (it blinks blue for 60 s), then:

```
python hello.py          # real band
python hello.py --sim    # pretend band, no hardware
```

With a Deepgram key set, the microphone's sound is sent to Deepgram. Tell people nearby.

`certfix.py` works around a broken certificate in the Windows certificate store
(`[ASN1: NOT_ENOUGH_DATA]`) by using certifi's CA bundle.
