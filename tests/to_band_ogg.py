"""Join WAV scenes (with gaps) and encode as Ogg Opus 16 kHz mono, 20 ms packets, like the band.
Usage: to_band_ogg.py OUT.ogg GAP_SECONDS in1.wav in2.wav ..."""
import sys

import av
import numpy as np

out_path, gap = sys.argv[1], float(sys.argv[2])
RATE = 16000
pieces = []
for p in sys.argv[3:]:
    with av.open(p) as f:
        res = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        for frame in f.decode(audio=0):
            for r in res.resample(frame):
                pieces.append(r.to_ndarray().reshape(-1))
        for r in res.resample(None):
            pieces.append(r.to_ndarray().reshape(-1))
    pieces.append(np.zeros(int(gap * RATE), dtype=np.int16))
pcm = np.concatenate(pieces).astype(np.int16)

out = av.open(out_path, "w", format="ogg")
st = out.add_stream("libopus", rate=RATE, options={"frame_duration": "20", "application": "voip"})
st.layout = "mono"
st.bit_rate = 16000                                    # ~40 bytes per packet, like the band
step = RATE // 50                                      # 320 samples = 20 ms
for i in range(0, len(pcm) - step + 1, step):
    fr = av.AudioFrame.from_ndarray(pcm[i:i + step].reshape(1, -1), format="s16", layout="mono")
    fr.sample_rate = RATE
    fr.pts = i
    for pkt in st.encode(fr):
        out.mux(pkt)
for pkt in st.encode(None):
    out.mux(pkt)
out.close()
print("wrote %s: %.1f s" % (out_path, len(pcm) / RATE))
