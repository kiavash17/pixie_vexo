"""Convert Playwright's WebM recording to an H.264 MP4 (plays everywhere).
Usage: to_mp4.py IN.webm OUT.mp4 [TRIM_SECONDS]   (TRIM cuts the blank page load at the start)"""
import sys
from fractions import Fraction

import av

src, dst = sys.argv[1], sys.argv[2]
trim = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
with av.open(src) as inp, av.open(dst, "w") as out:
    vin = inp.streams.video[0]
    fps = Fraction(25, 1)
    vout = out.add_stream("libx264", rate=fps)
    vout.width, vout.height = vin.codec_context.width, vin.codec_context.height
    vout.pix_fmt = "yuv420p"
    vout.options = {"crf": "20", "preset": "medium", "movflags": "+faststart"}
    vout.time_base = Fraction(1, 25)
    start = None
    last_pts = -1
    for frame in inp.decode(vin):
        t = float(frame.pts * vin.time_base) if frame.pts is not None else 0.0
        if t < trim:
            continue
        start = t if start is None else start
        pts = int(round((t - start) * 25))
        if pts <= last_pts:                       # keep timestamps increasing (variable frame rate input)
            continue
        last_pts = pts
        f = frame.reformat(format="yuv420p")
        f.pts, f.time_base = pts, Fraction(1, 25)
        for packet in vout.encode(f):
            out.mux(packet)
    for packet in vout.encode():
        out.mux(packet)
print("wrote %s" % dst)
