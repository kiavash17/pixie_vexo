# pixie_vexo

Hello world for the Vexo Open band (VexoHacks). It connects to band **06** (`Vexo-HACK-06`)
over Bluetooth and reads every sensor plus the microphone.

- **Phase 1 (10 s):** LED green; live accelerometer + gyroscope, taps/gestures, steps,
  battery, chip temperature, Bluetooth signal strength.
- **Phase 2 (10 s):** microphone on (the band's light is solid blue), loudness meter, voice
  saved to `hello.ogg`, and a live transcript through Deepgram when a key is set.

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
