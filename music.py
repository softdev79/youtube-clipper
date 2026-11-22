"""
Minimal background music, generated on the fly (no samples, no copyright claims).

A soft lo-fi bed: warm electric-piano chords, a round sub bass, a gentle kick and quiet hats,
with tape-style wobble and a little vinyl hiss. Each reel gets its own key, progression and
tempo from a seed, so a batch of reels doesn't all share one loop.

    import music
    music.generate("bed.wav", seconds=45, seed="reel title")

reel.render mixes it under the original audio and ducks it whenever the streamer talks.
"""
import hashlib
import wave

import numpy as np

SR = 48000

# chord progressions as scale-degree triads/sevenths (semitones above the key root)
PROGRESSIONS = [
    [[0, 3, 7, 10], [-4, 0, 3, 7], [-9, -5, -2, 3], [-2, 2, 5, 9]],      # i7  VImaj7  III  VII   (minor, moody)
    [[0, 4, 7, 11], [-3, 0, 4, 7], [5, 9, 12, 16], [-5, -1, 2, 5]],      # Imaj7 vi7 IVmaj7 V      (warm)
    [[0, 3, 7, 10], [5, 8, 12, 15], [-2, 2, 5, 9], [-4, 0, 3, 7]],       # i7  iv7  VII  VI       (late night)
    [[0, 4, 7, 11], [4, 7, 11, 14], [-3, 0, 4, 7], [5, 9, 12, 16]],      # Imaj7 iii7 vi7 IVmaj7  (dreamy)
]
KEYS = [57, 58, 60, 62, 53, 55]          # MIDI roots: A, Bb, C, D, F, G


def _hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _rng(seed):
    h = hashlib.sha1(str(seed).encode("utf-8")).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "little"))


def _lp_fast(x, cutoff):
    """one-pole low-pass using scipy if present, else a cheap FFT brick-wall."""
    try:
        from scipy.signal import lfilter
        a = np.exp(-2 * np.pi * cutoff / SR)
        return lfilter([1 - a], [1, -a], x)
    except Exception:  # noqa: BLE001
        X = np.fft.rfft(x)
        f = np.fft.rfftfreq(len(x), 1 / SR)
        X *= 1 / np.sqrt(1 + (f / cutoff) ** 4)
        return np.fft.irfft(X, len(x))


def _env(n, attack, release):
    e = np.ones(n)
    a, r = min(n, int(attack * SR)), min(n, int(release * SR))   # notes clipped at the end can be short
    if a:
        e[:a] = np.linspace(0, 1, a) ** 2
    if r:
        e[-r:] *= np.linspace(1, 0, r) ** 1.5
    return e


def _epiano(freq, n, rng):
    """soft Rhodes-ish tone: sine + a touch of 2nd harmonic, slow decay, slight detune"""
    t = np.arange(n) / SR
    det = 1 + rng.uniform(-0.0015, 0.0015)
    tone = (np.sin(2 * np.pi * freq * det * t) + 0.18 * np.sin(2 * np.pi * 2 * freq * t)
            + 0.05 * np.sin(2 * np.pi * 3 * freq * t + 0.3))
    decay = np.exp(-t * 0.9)
    return tone * decay * _env(n, 0.012, 0.25)


def generate(path, seconds, seed="", bpm=None):
    rng = _rng(seed)
    bpm = bpm or int(rng.choice([72, 76, 80, 84, 88]))
    root = int(rng.choice(KEYS))
    prog = PROGRESSIONS[int(rng.integers(len(PROGRESSIONS)))]
    beat = 60.0 / bpm
    bar = 4 * beat
    n = int((seconds + 0.5) * SR)
    t = np.arange(n) / SR
    mix = np.zeros(n)

    # chords: one per bar, voiced around middle C, plus a light second hit on beat 3 (and of 2 sometimes)
    nbars = int(np.ceil(seconds / bar)) + 1
    for b in range(nbars):
        chord = prog[b % len(prog)]
        for hit, vel in ((0.0, 1.0), (2.5 if rng.random() < 0.5 else 2.0, 0.55)):
            s = int((b * bar + hit * beat) * SR)
            if s >= n:
                continue
            ln = min(n - s, int((bar - hit * beat) * SR) + int(0.3 * SR))
            for k, iv in enumerate(chord):
                strum = int(k * 0.012 * SR)
                if s + strum >= n:
                    continue
                m = min(ln, n - s - strum)
                mix[s + strum:s + strum + m] += 0.11 * vel * _epiano(_hz(root + iv), m, rng)
        # sub bass on the chord root
        s = int(b * bar * SR)
        if s < n:
            m = min(n - s, int(bar * SR))
            tb = np.arange(m) / SR
            f0 = _hz(root + chord[0] - 24)
            mix[s:s + m] += 0.16 * np.sin(2 * np.pi * f0 * tb) * _env(m, 0.02, 0.4) * np.exp(-tb * 0.35)

    # drums: soft kick on 1 and the "and" of 3, quiet hats on 8ths with swing, no snare (keeps it minimal)
    kick_len = int(0.35 * SR)
    tk = np.arange(kick_len) / SR
    kick = np.sin(2 * np.pi * (48 + 70 * np.exp(-tk * 28)) * tk) * np.exp(-tk * 9)
    hat_len = int(0.05 * SR)
    hat = rng.standard_normal(hat_len) * np.exp(-np.arange(hat_len) / SR * 90)
    hat = hat - _lp_fast(hat, 6000)
    nbeats = int(seconds / beat) + 2
    for i in range(nbeats):
        for frac, kind in ((0.0, "k"), (0.5, "h"), (0.0, "h")):
            pos = (i + frac + (0.06 if frac == 0.5 else 0)) * beat
            s = int(pos * SR)
            if s >= n:
                continue
            if kind == "k" and i % 4 in (0, 2) and not (i % 4 == 2 and rng.random() < 0.3):
                shift = int((0.5 * beat * SR)) if i % 4 == 2 else 0
                s2 = s + shift
                m = min(kick_len, n - s2)
                if m > 0:
                    mix[s2:s2 + m] += 0.30 * kick[:m]
            elif kind == "h":
                m = min(hat_len, n - s)
                mix[s:s + m] += (0.045 if frac else 0.03) * hat[:m]

    # tape wobble (slow pitch drift via a tiny resample) and warmth
    wob = 1 + 0.0025 * np.sin(2 * np.pi * 0.33 * t) + 0.0012 * np.sin(2 * np.pi * 1.7 * t)
    idx = np.clip(np.cumsum(wob) - 1, 0, n - 1)
    mix = np.interp(idx, np.arange(n), mix)
    mix = _lp_fast(mix, 5200)
    mix += 0.004 * _lp_fast(rng.standard_normal(n), 3000)      # vinyl hiss
    mix = np.tanh(mix * 1.4) / 1.4                            # gentle saturation

    # stereo: slight delay/width on the right
    d = int(0.011 * SR)
    left, right = mix, np.concatenate([np.zeros(d), mix[:-d]]) * 0.92 + mix * 0.08
    fade = _env(n, 1.2, 1.5)
    st = np.stack([left * fade, right * fade], 1)
    st /= max(1e-9, np.abs(st).max()) / 0.7
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())
    return path
