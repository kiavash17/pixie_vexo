"""Turn Playwright's WebM phone recording into an H.264 MP4.

  to_mp4.py IN.webm OUT.mp4 [TRIM_SECONDS]                          portrait: the phone as recorded
  to_mp4.py IN.webm OUT.mp4 TRIM --landscape captions.json          1920x1080: phone centered at full
                                                                    height in a bezel, step title on the
                                                                    left, Pixie wordmark on the right
TRIM cuts the blank page load at the start. captions.json: [{"t": seconds since recording start, "text"}].
  ... --audio voice.json    adds a voice-over track: [{"t": seconds since recording start, "path": WAV}]
"""
import json
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 25
SUN, INK, DIM, TOMATO, CREAM, PEACH, MINT = "#ffc83d", "#2b2240", "#5d5270", "#f0583a", "#fff8ec", "#ffd9a8", "#d7f0e0"
PHONE_H = 940                                   # screen height in the frame (~87% of 1080)
BEZEL, SCREEN_R = 16, 46


def font(names, size):
    for n in names:
        for folder in (Path("C:/Windows/Fonts"), Path("/System/Library/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
            p = folder / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


BOLD = ["segoeuib.ttf", "Arialbd.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
REG = ["segoeui.ttf", "Arial.ttf", "arial.ttf", "DejaVuSans.ttf"]


def wrap(draw, text, fnt, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def star(draw, cx, cy, r, fill):
    pts = [(cx, cy - r), (cx + r * .28, cy - r * .28), (cx + r, cy), (cx + r * .28, cy + r * .28),
           (cx, cy + r), (cx - r * .28, cy + r * .28), (cx - r, cy), (cx - r * .28, cy - r * .28)]
    draw.polygon(pts, fill=fill)


class Landscape:
    def __init__(self, src_w, src_h, captions):
        self.sw = round(src_w * PHONE_H / src_h)
        self.sh = PHONE_H
        fw, fh = self.sw + 2 * BEZEL, self.sh + 2 * BEZEL
        self.fx, self.fy = (W - fw) // 2, (H - fh) // 2 - 6
        self.captions = captions
        base = Image.new("RGB", (W, H), SUN)
        d = ImageDraw.Draw(base)
        d.ellipse((-160, 640, 420, 1180), fill=PEACH)                     # soft background shapes
        d.ellipse((1560, -180, 2100, 330), fill=MINT)
        d.rounded_rectangle((self.fx, self.fy + 12, self.fx + fw, self.fy + fh + 12), 64, fill="#d9a31f")   # block edge
        d.rounded_rectangle((self.fx, self.fy, self.fx + fw, self.fy + fh), 64, fill=INK)                    # bezel
        # right panel: wordmark + tagline
        rx = self.fx + fw + 90
        star(d, rx + 26, 380, 26, TOMATO)
        d.text((rx + 66, 340), "Pixie", font=font(BOLD, 76), fill=INK)
        tag = font(REG, 30)
        y = 455
        for line in wrap(d, "A screenless help band for kids.", tag, W - rx - 80) + [""] + \
                wrap(d, "Double-tap twice = \u201cI need you.\u201d", tag, W - rx - 80):
            d.text((rx, y), line, font=tag, fill=DIM)
            y += 42
        self.base = base
        self.mask = Image.new("L", (self.sw, self.sh), 0)
        ImageDraw.Draw(self.mask).rounded_rectangle((0, 0, self.sw - 1, self.sh - 1), SCREEN_R, fill=255)
        self.panels = {}

    def panel(self, idx):
        """Left panel for caption idx: step label, big title, progress dots."""
        if idx in self.panels:
            return self.panels[idx]
        pw = self.fx - 170
        img = Image.new("RGBA", (pw, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if idx >= 0:
            c = self.captions[idx]
            # captions may carry their own numbering ("Feature 3 of 10"); otherwise every caption is a step
            n, k = (c["total"], c["n"]) if "n" in c else (len(self.captions), idx + 1)
            label = c.get("label") or ("STEP %d OF %d" % (k, n))
            title = font(BOLD, 58)
            lines = wrap(d, c["text"], title, pw - 20)
            y = H // 2 - (len(lines) * 72) // 2
            d.text((0, y - 70), label.upper(), font=font(BOLD, 24), fill=TOMATO)
            for line in lines:
                d.text((0, y), line, font=title, fill=INK)
                y += 72
            if c.get("sub"):
                for line in wrap(d, c["sub"], font(REG, 28), pw - 20):
                    d.text((0, y + 8), line, font=font(REG, 28), fill=DIM)
                    y += 38
                y += 8
            for i in range(n):                                            # progress dots
                x = i * 30
                d.ellipse((x, y + 40, x + 16, y + 56), fill=INK if i < k else "#e8b52d")
        self.panels[idx] = img
        return img

    def compose(self, phone_img, t):
        idx = max([i for i, c in enumerate(self.captions) if c["t"] <= t] or [-1])
        frame = self.base.copy()
        screen = phone_img.resize((self.sw, self.sh), Image.LANCZOS)
        frame.paste(screen, (self.fx + BEZEL, self.fy + BEZEL), self.mask)
        p = self.panel(idx)
        frame.paste(p, (110, 0), p)
        return frame


AUDIO_RATE = 48000


def voice_track(entries, start, seconds):
    """Mix the voice-over lines into one mono float track; entry times are on the recording clock."""
    mix = np.zeros(int(seconds * AUDIO_RATE), np.float32)
    for e in entries:
        with av.open(e["path"]) as f:
            res = av.AudioResampler(format="flt", layout="mono", rate=AUDIO_RATE)
            pcm = np.concatenate([r.to_ndarray().reshape(-1) for fr in f.decode(audio=0) for r in res.resample(fr)])
        at = int(max(0.0, e["t"] - start) * AUDIO_RATE)
        pcm = pcm[:max(0, len(mix) - at)]
        mix[at:at + len(pcm)] += pcm
    return np.clip(mix, -1, 1)


def audio_stream(out):
    aout = out.add_stream("aac", rate=AUDIO_RATE)
    aout.layout = "mono"
    aout.bit_rate = 128000
    return aout


def add_audio(out, aout, mix):
    for i in range(0, len(mix), 1024):
        fr = av.AudioFrame.from_ndarray(mix[i:i + 1024].reshape(1, -1), format="fltp", layout="mono")
        fr.sample_rate, fr.pts = AUDIO_RATE, i
        for p in aout.encode(fr):
            out.mux(p)
    for p in aout.encode(None):
        out.mux(p)


def find_flash(src):
    """Video-clock time of the first magenta frame (the sync marker), or None."""
    with av.open(src) as f:
        s = f.streams.video[0]
        for fr in f.decode(s):
            r, g, b = fr.to_ndarray(format="rgb24")[::40, ::40].reshape(-1, 3).mean(0)
            if r > 200 and g < 60 and b > 200:
                return float(fr.pts * s.time_base)
            if fr.pts * s.time_base > 30:
                return None
    return None


def main():
    src, dst = sys.argv[1], sys.argv[2]
    trim = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    caps = voice = None
    if "--landscape" in sys.argv:
        caps = json.loads(Path(sys.argv[sys.argv.index("--landscape") + 1]).read_text(encoding="utf-8"))
    if "--audio" in sys.argv:
        voice = json.loads(Path(sys.argv[sys.argv.index("--audio") + 1]).read_text(encoding="utf-8"))
    # --sync SECONDS: when the script showed the magenta flash; the recording's own clock can start late
    offset = 0.0
    if "--sync" in sys.argv:
        flash = find_flash(src)
        if flash is None:
            print("sync marker not found; using the recording's clock as is")
        else:
            offset = float(sys.argv[sys.argv.index("--sync") + 1]) - flash
            print("recording clock is %.2f s behind the script's" % offset)
    with av.open(src) as inp, av.open(dst, "w") as out:
        vin = inp.streams.video[0]
        vout = out.add_stream("libx264", rate=FPS)
        if caps is not None:
            vout.width, vout.height = W, H
            land = Landscape(vin.codec_context.width, vin.codec_context.height, caps)
        else:                                         # portrait: 2x the 390x844 phone -> 780x1688
            vout.width, vout.height = vin.codec_context.width * 2, vin.codec_context.height * 2
        vout.pix_fmt = "yuv420p"
        vout.options = {"crf": "20", "preset": "medium", "movflags": "+faststart"}
        vout.time_base = Fraction(1, FPS)
        aout = audio_stream(out) if voice else None
        start, last_pts = None, -1
        for frame in inp.decode(vin):
            t = (float(frame.pts * vin.time_base) if frame.pts is not None else 0.0) + offset   # script clock
            if t < trim:
                continue
            start = t if start is None else start
            pts = int(round((t - start) * FPS))
            if pts <= last_pts:                       # keep timestamps increasing (variable frame rate input)
                continue
            last_pts = pts
            if caps is not None:
                f = av.VideoFrame.from_image(land.compose(frame.to_image(), t))
            else:
                f = av.VideoFrame.from_image(frame.to_image().resize((vout.width, vout.height), Image.LANCZOS))
            f = f.reformat(format="yuv420p")
            f.pts, f.time_base = pts, Fraction(1, FPS)
            for packet in vout.encode(f):
                out.mux(packet)
        for packet in vout.encode():
            out.mux(packet)
        if voice:
            add_audio(out, aout, voice_track(voice, start or 0.0, (last_pts + 1) / FPS))
    print("wrote %s" % dst)


if __name__ == "__main__":
    main()
