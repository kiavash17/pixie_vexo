"""Turn Playwright's WebM phone recording into an H.264 MP4.

  to_mp4.py IN.webm OUT.mp4 [TRIM_SECONDS]                          portrait: the phone as recorded
  to_mp4.py IN.webm OUT.mp4 TRIM --landscape captions.json          1920x1080: phone centered at full
                                                                    height in a bezel, step title on the
                                                                    left, Pixie wordmark on the right
TRIM cuts the blank page load at the start. captions.json: [{"t": seconds since recording start, "text"}].
"""
import json
import sys
from fractions import Fraction
from pathlib import Path

import av
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
            n = len(self.captions)
            title = font(BOLD, 58)
            lines = wrap(d, self.captions[idx]["text"], title, pw - 20)
            y = H // 2 - (len(lines) * 72) // 2
            d.text((0, y - 70), "STEP %d OF %d" % (idx + 1, n), font=font(BOLD, 24), fill=TOMATO)
            for line in lines:
                d.text((0, y), line, font=title, fill=INK)
                y += 72
            for i in range(n):                                            # progress dots
                x = i * 30
                d.ellipse((x, y + 40, x + 16, y + 56), fill=INK if i <= idx else "#e8b52d")
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


def main():
    src, dst = sys.argv[1], sys.argv[2]
    trim = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    caps = None
    if "--landscape" in sys.argv:
        caps = json.loads(Path(sys.argv[sys.argv.index("--landscape") + 1]).read_text(encoding="utf-8"))
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
        start, last_pts = None, -1
        for frame in inp.decode(vin):
            t = float(frame.pts * vin.time_base) if frame.pts is not None else 0.0
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
    print("wrote %s" % dst)


if __name__ == "__main__":
    main()
