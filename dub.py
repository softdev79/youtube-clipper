"""
Dubbing: turn a clip into another language (Hindi -> English, English -> Hindi, ...), keeping the game/music.

Pipeline for one source clip (the downloaded range of a reel):
  1. Lines: what is said and when, from the video's captions (`script_lines`). Claude (or you) translates
     each line; spoken text in the target script (Devanagari for Hindi = best pronunciation), plus an optional
     Roman-script caption.
  2. Voice: each line is spoken by a neural voice (edge-tts, free, no account) and fitted to its slot: faster
     speaking rate first, then a small tempo change, so the dub stays in sync with the speaker.
  3. Music/game sound: the original audio is split into voice and background with Demucs (if installed). The
     background is kept; the original voice is muted while the dub speaks and kept elsewhere (screams, laughs).
     Without Demucs the original is ducked under the dub.
  4. Optional lip-sync (lipsync.py): re-renders the mouth to match the new voice (cloud, needs an API key).

Reel spec field (plan.json):
  "dub": {"lang": "hi", "voice": "hi-IN-MadhurNeural", "rate": "+5%", "lipsync": "none" | "sync",
          "speakers": {"speed": "hi-IN-MadhurNeural", "lucia": "hi-IN-SwaraNeural"},   # optional
          "lines": [[abs_start, abs_end, "spoken text", "caption text", "original", "speaker", "mood"], ...]}
  mood = normal | excited | shout | savage | sarcastic | sad | whisper | deadpan (pitch/speed/volume per line).
  Lines may also sit in silent gaps (asides to the viewer, roasts) - they don't need an original.
  Multilingual voices (en-US-BrianMultilingualNeural, en-US-AndrewMultilingualNeural, ...) can speak Hindi
  too, which gives extra distinct voices when several people talk.
"""
import asyncio
import os
import re
import subprocess
import tempfile

import numpy as np

import clipper
from clipper import parse_time

SR = 44100
FFMPEG_EXE = os.path.join(clipper.FFMPEG, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")

VOICES = {  # target language -> (male, female) edge-tts voices
    "hi": ("hi-IN-MadhurNeural", "hi-IN-SwaraNeural"),
    "en": ("en-US-GuyNeural", "en-US-AriaNeural"),
    "en-us": ("en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural"),
    "en-in": ("en-IN-PrabhatNeural", "en-IN-NeerjaNeural"),
    "bn": ("bn-IN-BashkarNeural", "bn-IN-TanishaaNeural"),
    "ta": ("ta-IN-ValluvarNeural", "ta-IN-PallaviNeural"),
    "te": ("te-IN-MohanNeural", "te-IN-ShrutiNeural"),
    "mr": ("mr-IN-ManoharNeural", "mr-IN-AarohiNeural"),
    "gu": ("gu-IN-NiranjanNeural", "gu-IN-DhwaniNeural"),
    "ur": ("ur-IN-SalmanNeural", "ur-IN-GulNeural"),
    "es": ("es-MX-JorgeNeural", "es-MX-DaliaNeural"),
    "pt": ("pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"),
    "fr": ("fr-FR-HenriNeural", "fr-FR-DeniseNeural"),
    "de": ("de-DE-ConradNeural", "de-DE-KatjaNeural"),
    "ar": ("ar-SA-HamedNeural", "ar-SA-ZariyahNeural"),
    "ja": ("ja-JP-KeitaNeural", "ja-JP-NanamiNeural"),
}
MAX_RATE = 65      # % faster speaking rate edge-tts may use to fit a slot
MAX_TEMPO = 1.25   # extra time-stretch after that


def voice_for(lang, gender="male"):
    pair = VOICES.get(lang.lower()) or VOICES.get(lang.lower().split("-")[0]) or VOICES["en"]
    return pair[1] if gender == "female" else pair[0]


def _run(args):
    r = subprocess.run([FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y"] + args,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError("ffmpeg: " + r.stderr[-600:])


def _read(path, channels=1):
    r = subprocess.run([FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-ac", str(channels),
                        "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if r.returncode:
        raise RuntimeError("ffmpeg could not read audio from " + path)
    a = np.frombuffer(r.stdout, dtype=np.float32)
    return a.reshape(-1, channels).T.copy()  # (channels, samples)


def _write_wav(path, audio):
    a = np.clip(audio, -1, 1)
    pcm = (a.T * 32767).astype("<i2").tobytes()
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(a.shape[0])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)


# ---------------------------------------------------------------- 1. lines to translate
def script_lines(words, start, end, cuts=None, pause=0.6, max_words=14):
    """Utterances inside [start, end] (absolute seconds), skipping jump-cut ranges."""
    import transcript
    cut = [(parse_time(a), parse_time(b)) for a, b in (cuts or [])]
    inside = [w for w in words if start <= w[0] < end and not any(a <= w[0] < b for a, b in cut)]
    out = []
    for u in transcript.utterances(inside, pause=pause, max_words=max_words):
        out.append([round(u["start"], 2), round(min(u["end"], end), 2), u["text"]])
    return out


# ---------------------------------------------------------------- 2. voice
# Delivery per line (7th field of a dub line): speaking-rate %, pitch Hz, volume %.
MOODS = {  # relative to the dub's base rate; neural voices are slow by default, so moods stay close to it
    "normal": (0, 0, 0),
    "excited": (10, 6, 10),     # hype, fast and bright
    "shout": (12, 12, 25),      # yelling, panic, "BHAI NAHI!"
    "savage": (4, -3, 8),       # roast / punchline, confident, slightly low
    "sarcastic": (-2, -5, 0),   # dry, eye-roll
    "sad": (-6, -9, -10),       # heartbreak, a bit slower and low
    "whisper": (0, -2, -35),    # aside to the viewer
    "deadpan": (0, -8, 0),      # flat, comedic understatement
}


async def _tts_async(text, voice, rate, path, pitch="+0Hz", volume="+0%"):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume).save(path)


def tts(text, voice, rate, path, pitch="+0Hz", volume="+0%"):
    """Speak `text`; retries, then falls back to the other default voice of the same language."""
    import time
    lang = "-".join(voice.split("-")[:2]).lower()
    backups = [v for pair in VOICES.values() for v in pair if v.lower().startswith(lang) and v != voice]
    err = None
    for k, v in enumerate([voice] * 4 + backups[:1]):
        try:
            asyncio.run(_tts_async(text, v, rate, path, pitch, volume))
            if os.path.getsize(path) > 0:
                return _read(path)[0]
        except Exception as e:  # noqa: BLE001  (the free service rate-limits bursts: back off)
            err = e
            time.sleep(2 + 3 * k)
    raise RuntimeError(f"Text-to-speech failed for '{text[:40]}': {err}")


_tts = tts


def _trim_silence(a, thr=0.01):
    idx = np.where(np.abs(a) > thr)[0]
    if not len(idx):
        return a
    return a[max(0, idx[0] - int(0.02 * SR)): idx[-1] + int(0.05 * SR)]


def _pct(s):
    m = re.match(r"([+-]?\d+)%", s or "+0%")
    return int(m.group(1)) if m else 0


def speak_lines(lines, voice, base_rate, clip_start, clip_end, tmp, log=print):
    """-> list of (offset_sec_in_clip, mono samples) fitted to each line's slot."""
    out, base = [], _pct(base_rate)

    def tts(text, v, rate, path):  # a speaker's voice failing falls back to the main dub voice
        try:
            return _tts(text, v, rate, path, pitch, vol)
        except RuntimeError:
            if v == voice:
                raise
            log(f"    voice {v} failed, using {voice} for: {text[:30]}")
            return _tts(text, voice, rate, path, pitch, vol)

    for i, ln in enumerate(lines):
        s, e, text = float(ln[0]), float(ln[1]), str(ln[2]).strip()
        v = ln[3] if len(ln) > 3 and ln[3] else voice
        mr, mp, mv = MOODS.get((ln[4] if len(ln) > 4 and ln[4] else "normal"), MOODS["normal"])
        pitch, vol = f"{mp:+d}Hz", f"{mv:+d}%"
        if not text:
            continue
        nxt = float(lines[i + 1][0]) if i + 1 < len(lines) else clip_end
        slot = max(0.4, min(nxt, clip_end) - s - 0.05)
        p = os.path.join(tmp, f"tts_{i:03d}.mp3")
        r0 = base + mr
        a = _trim_silence(tts(text, v, f"{r0:+d}%", p))
        dur = len(a) / SR
        if dur > slot:  # speak faster
            need = min(MAX_RATE, r0 + int(np.ceil((dur / slot - 1) * 100)) + 3)
            if need > r0:
                a = _trim_silence(tts(text, v, f"{need:+d}%", p))
                dur = len(a) / SR
        if dur > slot:  # then a small time-stretch
            k = min(MAX_TEMPO, dur / slot)
            src, dst = p + ".wav", p + ".fast.wav"
            _write_wav(src, a[None])
            _run(["-i", src, "-filter:a", f"atempo={k:.3f}", dst])
            a = _read(dst)[0]
            dur = len(a) / SR
            if dur > slot + 0.3:
                log(f"    line {i + 1} is {dur - slot:.1f}s too long for its slot: shorten the translation")
        out.append((s - clip_start, a))
    return out


# ---------------------------------------------------------------- 3. separate + mix
def separate(audio_st, log=print):
    """(2, n) stereo -> (background, vocals) with Demucs htdemucs, or None if Demucs isn't installed."""
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except ImportError:
        return None
    log("    separating voice from game sound (Demucs)…")
    model = get_model("htdemucs")
    model.eval()
    wav = torch.from_numpy(audio_st)
    if model.samplerate != SR:
        raise RuntimeError("unexpected Demucs sample rate")
    ref = wav.mean(0)
    mu, sd = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        src = apply_model(model, ((wav - mu) / sd)[None], device="cpu", split=True, overlap=0.25,
                          progress=False, num_workers=0)[0]
    src = src * sd + mu
    vi = model.sources.index("vocals")
    vocals = src[vi].numpy()
    bg = (src.sum(0) - src[vi]).numpy()
    return bg, vocals


def _gate(n, spans, fade=0.08):
    """1 outside the dub spans, 0 inside (with short fades)."""
    g = np.ones(n, dtype=np.float32)
    f = int(fade * SR)
    for a, b in spans:
        a, b = max(0, int(a * SR)), min(n, int(b * SR))
        if b <= a:
            continue
        g[a:b] = 0
        lo = max(0, a - f)
        g[lo:a] = np.minimum(g[lo:a], np.linspace(1, 0, a - lo))
        hi = min(n, b + f)
        g[b:hi] = np.minimum(g[b:hi], np.linspace(0, 1, hi - b))
    return g


def dub_clip(src, out, spec, tmp=None, log=print):
    """Write `out`: the same video with the dubbed audio. Returns info dict."""
    d = spec["dub"]
    tmp = tmp or tempfile.mkdtemp(prefix="dub_")
    start, end = parse_time(str(spec["start"])), parse_time(str(spec["end"]))
    lines = [ln for ln in d.get("lines", []) if len(ln) >= 3 and str(ln[2]).strip()]
    if not lines:
        raise ValueError("dub.lines is empty: translate the lines first")
    voice = d.get("voice") or voice_for(d.get("lang", "en"), d.get("gender", "male"))
    log(f"    dubbing {len(lines)} lines with {voice}…")
    orig = _read(src, 2)
    n = orig.shape[1]
    clip_end = start + n / SR
    speakers = d.get("speakers") or {}

    def line_voice(ln):  # 6th field: speaker name (from dub.speakers) or a voice name
        who = ln[5] if len(ln) > 5 and ln[5] else None
        return speakers.get(who, who) if who else voice

    def mood(ln):  # 7th field: delivery (see MOODS)
        return ln[6] if len(ln) > 6 and ln[6] else d.get("mood", "normal")

    said = speak_lines([[float(ln[0]) if not isinstance(ln[0], str) else parse_time(ln[0]),
                         float(ln[1]) if not isinstance(ln[1], str) else parse_time(ln[1]), ln[2], line_voice(ln), mood(ln)]
                        for ln in lines], voice, d.get("rate", "+28%"), start, clip_end, tmp, log)
    voice_trk = np.zeros(n, dtype=np.float32)
    spans = []
    for off, a in said:
        i = int(max(0, off) * SR)
        j = min(n, i + len(a))
        voice_trk[i:j] += a[: j - i]
        spans.append((off, off + len(a) / SR))
    # merge orig-speech spans with dub spans so no English (or source language) leaks through
    for a, b, *_ in lines:
        a = (float(a) if not isinstance(a, str) else parse_time(a)) - start
        b = (float(b) if not isinstance(b, str) else parse_time(b)) - start
        spans.append((a - 0.05, b + 0.1))
    peak = np.abs(voice_trk).max() or 1
    voice_trk *= 0.89 / peak
    sep = None if d.get("separate") is False else separate(orig, log)
    if sep is not None:
        bg, vocals = sep
        keep = float(d.get("keep_original_voice", 0.85))  # screams/laughs between lines
        mix = bg + vocals * _gate(n, spans)[None] * keep + voice_trk[None] * float(d.get("voice_gain", 1.0))
        method = "demucs"
    else:
        duck = np.where(_gate(n, spans) < 0.5, 0.12, 0.8).astype(np.float32)
        mix = orig * duck[None] + voice_trk[None]
        method = "ducking"
    wav = os.path.join(tmp, "dub_mix.wav")
    _write_wav(wav, mix / max(1.0, np.abs(mix).max() / 0.98))
    voice_wav = os.path.join(tmp, "dub_voice.wav")
    _write_wav(voice_wav, voice_trk[None])
    _run(["-i", src, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
          "-shortest", out])
    return {"file": out, "voice": voice, "lines": len(lines), "background": method, "voice_track": voice_wav}


def caption_lines(spec, max_chars=26):
    """Captions for a dubbed reel: the translated lines, split into short chunks timed by length."""
    caps = []
    for ln in spec["dub"].get("lines", []):
        if len(ln) < 3:
            continue
        a = float(ln[0]) if not isinstance(ln[0], str) else parse_time(ln[0])
        b = float(ln[1]) if not isinstance(ln[1], str) else parse_time(ln[1])
        text = str(ln[3] if len(ln) > 3 and ln[3] else ln[2]).strip()
        words, chunks, cur = text.split(), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                chunks.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            chunks.append(cur)
        total = sum(len(c) for c in chunks) or 1
        t = a
        for c in chunks:
            dt = (b - a) * len(c) / total
            caps.append([round(t, 2), round(t + dt, 2), c])
            t += dt
    return caps
