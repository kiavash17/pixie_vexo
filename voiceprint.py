"""
Voiceprint: is this the enrolled child's voice? Pitch + timbre, not loudness.

A voiceprint is computed from 16 kHz int16 samples:
  - timbre: the average log-mel spectrum of the voiced frames, with overall loudness removed
    (so near / far / loud / quiet does not matter), plus how much each band varies;
  - pitch: the median fundamental frequency (F0) of the voiced frames.
Two voiceprints match when the timbre vectors are similar (cosine) AND the pitch is within a few
semitones. Everything runs locally with numpy in a few milliseconds.
"""
import numpy as np

RATE = 16000
FRAME, HOP = 400, 160                   # 25 ms windows, 10 ms hop
N_MELS = 26
SIM_MIN = 0.955                         # timbre similarity needed: own voice 0.98-1.00, others <= 0.92 in tests
PITCH_MAX_ST = 6.0                      # pitch difference allowed, in semitones (short clips are noisy)
MIN_VOICED = 25                         # voiced frames needed (~0.25 s of speech) to judge at all


def _mel_filters(n_fft=512, n_mels=N_MELS, fmin=80, fmax=7600):
    mel = lambda f: 2595 * np.log10(1 + f / 700)          # noqa: E731
    inv = lambda m: 700 * (10 ** (m / 2595) - 1)          # noqa: E731
    pts = inv(np.linspace(mel(fmin), mel(fmax), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / RATE).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for i in range(n_mels):
        a, b, c = bins[i], bins[i + 1], bins[i + 2]
        if b > a:
            fb[i, a:b] = (np.arange(a, b) - a) / (b - a)
        if c > b:
            fb[i, b:c] = (c - np.arange(b, c)) / (c - b)
    return fb


_FB = _mel_filters()
_WIN = np.hanning(FRAME)


def _pitch(frame):
    """F0 of one frame by autocorrelation (75-500 Hz), or None if it isn't clearly voiced."""
    x = frame - frame.mean()
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    if ac[0] <= 0:
        return None
    lo, hi = RATE // 500, RATE // 75
    lag = lo + int(np.argmax(ac[lo:hi]))
    return RATE / lag if ac[lag] / ac[0] > 0.45 else None


def compute(samples):
    """Voiceprint of a stretch of speech, or None if there is too little voiced speech."""
    x = np.asarray(samples, dtype=np.float64) / 32768.0
    if len(x) < FRAME * 4:
        return None
    n = 1 + (len(x) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx]
    energy = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    voiced = energy > max(np.percentile(energy, 40), energy.max() - 30)   # speech frames, not pauses
    if voiced.sum() < MIN_VOICED:
        return None
    spec = np.abs(np.fft.rfft(frames[voiced] * _WIN, 512)) ** 2
    logmel = np.log(spec @ _FB.T + 1e-10)
    logmel -= logmel.mean(axis=1, keepdims=True)                        # remove loudness per frame
    timbre = np.concatenate([logmel.mean(axis=0), 0.5 * logmel.std(axis=0)])
    pitches = [p for p in (_pitch(f) for f in frames[voiced][::3]) if p]
    return {"timbre": timbre.tolist(), "f0": float(np.median(pitches)) if pitches else None,
            "voiced_s": round(float(voiced.sum()) * HOP / RATE, 2)}


def load_file(path):
    """int16 samples at 16 kHz from any audio file (e.g. the saved enrollment clip)."""
    import av
    out = []
    with av.open(str(path)) as f:
        res = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        for frame in f.decode(audio=0):
            for r in res.resample(frame):
                out.append(r.to_ndarray().reshape(-1))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int16)


def compare(a, b):
    """(similarity 0-1, pitch difference in semitones or None)."""
    ta, tb = np.asarray(a["timbre"]), np.asarray(b["timbre"])
    ta, tb = ta - ta.mean(), tb - tb.mean()
    sim = float(ta @ tb / (np.linalg.norm(ta) * np.linalg.norm(tb) + 1e-9))
    st = None
    if a.get("f0") and b.get("f0"):
        st = float(abs(12 * np.log2(a["f0"] / b["f0"])))
    return round(sim, 3), (round(st, 2) if st is not None else None)


def is_match(probe, enrolled):
    """True / False, or None when there's not enough speech to tell. Also returns the numbers."""
    if not probe or not enrolled:
        return None, None, None
    sim, st = compare(probe, enrolled)
    ok = sim >= SIM_MIN and (st is None or st <= PITCH_MAX_ST)
    return ok, sim, st
