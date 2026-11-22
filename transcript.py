"""
Transcript helpers: fetch YouTube captions (manual or auto, original language), split them into
utterances, and snap clip boundaries to natural pauses so a clip carries its full context
(setup -> payoff) instead of cutting mid-sentence.
"""
import glob
import json
import os
import re
import tempfile

import yt_dlp

BASE_OPTS = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True}
SENT_END = re.compile(r"[.!?।]$")


# ---------------------------------------------------------------- fetching
def _pick_lang(info):
    """Prefer manual subs in the video's language, then the original-language auto captions."""
    subs = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    lang = (info.get("language") or "").split("-")[0]
    if lang and lang in subs:
        return lang, False
    orig = [k for k in auto if k.endswith("-orig")]
    if orig:
        return orig[0], True
    if subs:
        return next(iter(subs)), False
    for k in (lang, "en"):
        if k and k in auto:
            return k, True
    return None, None


def fetch_words(url, info=None, cache=None):
    """Return {"lang": str, "words": [[t_seconds, text], ...]} or None if the video has no captions.
    `cache` is an optional JSON path: reused if present, written after a download."""
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)
    if info is None:
        with yt_dlp.YoutubeDL(BASE_OPTS) as y:
            info = y.extract_info(url, download=False)
    lang, is_auto = _pick_lang(info)
    if not lang:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        opts = {**BASE_OPTS, "skip_download": True, "subtitleslangs": [lang], "subtitlesformat": "json3",
                "writeautomaticsub": bool(is_auto), "writesubtitles": not is_auto,
                "outtmpl": os.path.join(tmp, "t.%(ext)s")}
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([info.get("webpage_url") or url])
        files = glob.glob(os.path.join(tmp, "*.json3"))
        if not files:
            return None
        with open(files[0], encoding="utf-8") as fh:
            data = json.load(fh)
    words = []
    for ev in data.get("events", []):
        segs = [s for s in ev.get("segs") or [] if s.get("utf8", "").strip()]
        if not segs:
            continue
        t0, dur = ev.get("tStartMs", 0), ev.get("dDurationMs", 0)
        has_offsets = any("tOffsetMs" in s for s in segs)
        for i, s in enumerate(segs):
            off = s.get("tOffsetMs", 0) if has_offsets else (dur * i / len(segs))
            for j, w in enumerate(s["utf8"].split()):
                words.append([round((t0 + off) / 1000 + j * 0.05, 2), w])
    words.sort(key=lambda w: w[0])
    res = {"lang": lang, "auto": bool(is_auto), "words": words}
    if cache:
        os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False)
    return res


# ---------------------------------------------------------------- structure
def utterances(words, pause=0.9, max_words=16):
    """Group words into utterances split on pauses / sentence ends.
    Each: {"start", "end", "text", "pause_before", "pause_after"}."""
    out, cur = [], []
    for k, (t, w) in enumerate(words):
        if cur and (t - cur[-1][0] > pause or len(cur) >= max_words):
            out.append(cur)
            cur = []
        cur.append((t, w))
        if SENT_END.search(w) and len(cur) >= 3:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    utts = []
    for u in out:
        start = u[0][0]
        # a word lasts until the next one, capped at ~0.6 s for the last word
        end = u[-1][0] + 0.6
        utts.append({"start": start, "end": end, "text": " ".join(w for _, w in u)})
    for i, u in enumerate(utts):
        if i + 1 < len(utts):
            u["end"] = min(u["end"], utts[i + 1]["start"])
        u["pause_before"] = round(u["start"] - utts[i - 1]["end"], 2) if i else 99.0
        u["pause_after"] = round(utts[i + 1]["start"] - u["end"], 2) if i + 1 < len(utts) else 99.0
    return utts


def lines_between(utts, a, b):
    return [u for u in utts if u["end"] > a and u["start"] < b]


def text_between(utts, a, b):
    return " ".join(u["text"] for u in lines_between(utts, a, b))


# ---------------------------------------------------------------- boundary snapping
def snap_bounds(utts, peak, min_len=20, max_len=90, lead_min=8, tail_min=10, duration=None):
    """Pick (start, end) around `peak` so the clip starts at a natural break before the setup and
    ends at a natural break after the payoff. Falls back to a centred window if there are no captions
    near the peak. Bigger pauses are treated as stronger topic boundaries."""
    D = duration or 10 ** 9
    near = lines_between(utts, peak - max_len, peak + max_len)
    if not near:
        s = max(0, peak - min_len * 0.4)
        return s, min(D, s + min_len)

    # start: the utterance start with the biggest pause before it, within [peak-max_len+tail, peak-lead_min]
    lo = peak - (max_len - tail_min - 6)
    starts = [u for u in near if lo <= u["start"] <= peak - lead_min]
    if starts:
        best = max(starts, key=lambda u: (min(u["pause_before"], 8), -abs(peak - u["start"] - 25) / 100))
        start = best["start"]
    else:
        start = max(0, peak - lead_min - 4)

    # end: the utterance end with the biggest pause after it, within [peak+tail_min, start+max_len]
    hi = start + max_len
    ends = [u for u in near if peak + tail_min <= u["end"] <= hi and u["end"] - start >= min_len]
    if ends:
        best = max(ends, key=lambda u: (min(u["pause_after"], 8), -u["end"] / 1e6))
        end = best["end"]
    else:
        end = min(hi, max(start + min_len, peak + tail_min + 6))

    start = max(0.0, start - 0.25)
    end = min(D, end + 0.5)
    if end - start < min_len:
        end = min(D, start + min_len)
    return round(start, 2), round(end, 2)


def clean_words(ws):
    """Drop YouTube auto-caption markup: '>>' speaker changes, [music]/[laughter]/[clears throat] tags;
    the censored-swear token '[ __ ]' becomes '****'."""
    out, in_tag = [], False
    for t, w in ws:
        if in_tag:
            in_tag = not w.endswith("]")
            continue
        if w == ">>" or w in ("[", "]"):
            continue
        if w == "__":
            out.append((t, "****"))
            continue
        if w.startswith("["):
            in_tag = not w.endswith("]")
            continue
        out.append((t, w.replace(">>", "").strip() or None))
    return [(t, w) for t, w in out if w]


def chunk_captions(words, a, b, max_words=4, max_gap=0.8, max_dur=2.2):
    """Short on-screen caption chunks [(start, end, text)] for words in [a, b) (absolute seconds)."""
    ws = clean_words([(t, w) for t, w in words if a <= t < b])
    chunks, cur = [], []
    for i, (t, w) in enumerate(ws):
        if cur and (len(cur) >= max_words or t - cur[-1][0] > max_gap or t - cur[0][0] > max_dur):
            chunks.append(cur)
            cur = []
        cur.append((t, w))
        if SENT_END.search(w):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        s = c[0][0]
        nxt = chunks[i + 1][0][0] if i + 1 < len(chunks) else b
        e = min(nxt, c[-1][0] + 0.9, b)
        out.append((round(s, 2), round(max(e, s + 0.4), 2), " ".join(w for _, w in c)))
    return out
