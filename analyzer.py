"""
Find the most engaging moments of a YouTube video / past live stream.

Signals (each turned into a per-second curve, smoothed, normalised to 0..1, then combined):
  * heatmap   - YouTube "Most replayed" graph  -> where people re-watch / watch time peaks
  * chat      - live-chat replay messages/sec   -> where the stream chat exploded
  * comments  - timestamps people write in comments ("2:31:05 lmao"), weighted by likes

Then the top-N peaks are picked greedily so that clips never overlap (plus a minimum gap).
"""
import glob
import json
import math
import os
import re
import shutil
import tempfile

import yt_dlp

TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?![\d:])")
CHAT_LAG = 8          # chat reacts a few seconds AFTER the moment happens -> shift it earlier
WEIGHTS = {"heatmap": 1.0, "chat": 1.0, "comments": 0.8}
BASE_OPTS = {"quiet": True, "no_warnings": True, "noplaylist": True}


# ---------------------------------------------------------------- signal loaders
def heatmap_curve(info, D):
    hm = info.get("heatmap") or []
    if not hm:
        return None
    # linear interpolation between segment centres, so peaks land in the middle of a segment
    pts = [((h["start_time"] + h["end_time"]) / 2, float(h["value"])) for h in hm]
    curve = [0.0] * D
    j = 0
    for t in range(D):
        while j < len(pts) - 2 and pts[j + 1][0] < t:
            j += 1
        (t0, v0), (t1, v1) = pts[j], pts[min(j + 1, len(pts) - 1)]
        if t <= t0:
            curve[t] = v0
        elif t >= t1:
            curve[t] = v1
        else:
            curve[t] = v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return curve


def _chat_text(action):
    item = action.get("addChatItemAction", {}).get("item", {})
    for key in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
        r = item.get(key)
        if r:
            runs = r.get("message", {}).get("runs", [])
            text = "".join(x.get("text") or x.get("emoji", {}).get("shortcuts", [""])[0] for x in runs)
            return text.strip(), key == "liveChatPaidMessageRenderer"
    return None, False


def load_chat(url, D, progress):
    """Download live-chat replay; returns (curve, messages[(t, text)]) or (None, [])."""
    tmp = tempfile.mkdtemp(prefix="ytchat_")

    def hook(d):
        if d.get("status") == "downloading":
            mb = (d.get("downloaded_bytes") or 0) / 1e6
            progress(f"Downloading live-chat replay… {mb:.1f} MB")

    try:
        opts = dict(BASE_OPTS, skip_download=True, writesubtitles=True,
                    subtitleslangs=["live_chat"], outtmpl=os.path.join(tmp, "chat"),
                    progress_hooks=[hook], noprogress=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = glob.glob(os.path.join(tmp, "*.live_chat.json"))
        if not files:
            return None, []
        curve = [0.0] * D
        msgs = []
        with open(files[0], encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                rep = obj.get("replayChatItemAction")
                if not rep:
                    continue
                t = int(int(rep.get("videoOffsetTimeMsec", 0)) / 1000) - CHAT_LAG
                if not 0 <= t < D:
                    continue
                for act in rep.get("actions", []):
                    text, paid = _chat_text(act)
                    if text is None:
                        continue
                    curve[t] += 3.0 if paid else 1.0   # super-chats count more
                    if text:
                        msgs.append((t, text))
        return (curve if any(curve) else None), msgs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_comments(url, D, max_comments=1000):
    opts = dict(BASE_OPTS, getcomments=True, extractor_args={
        "youtube": {"max_comments": [str(max_comments), str(max_comments), "0"],
                    "comment_sort": ["top"]}})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    curve = [0.0] * D
    refs = []
    for c in info.get("comments") or []:
        text = c.get("text") or ""
        found = list(TS_RE.finditer(text))
        if not found:
            continue
        # likes boost; a "chapter list" comment with many timestamps shouldn't dominate
        w = (1.0 + math.log1p(max(0, c.get("like_count") or 0))) / math.sqrt(len(found))
        for mt in found:
            h, m, s = mt.groups()
            t = int(h or 0) * 3600 + int(m) * 60 + int(s)
            if 0 <= t < D:
                curve[t] += w
                # snippet = the line containing this timestamp
                ls = text.rfind("\n", 0, mt.start()) + 1
                le = text.find("\n", mt.end())
                snippet = text[ls:le if le != -1 else len(text)].strip()[:120]
                refs.append((t, w, snippet))
    return (curve if any(curve) else None), refs, len(info.get("comments") or [])


# ---------------------------------------------------------------- maths helpers
def smooth(curve, width):
    """Centred moving average (prefix sums, O(n))."""
    n, half = len(curve), max(1, width // 2)
    pre = [0.0]
    for v in curve:
        pre.append(pre[-1] + v)
    return [(pre[min(n, i + half + 1)] - pre[max(0, i - half)]) / (min(n, i + half + 1) - max(0, i - half))
            for i in range(n)]


def normalise(curve):
    mx = max(curve) if curve else 0
    return [v / mx for v in curve] if mx > 0 else curve


def downsample(curve, points=400):
    n = len(curve)
    if n <= points:
        return curve
    step = n / points
    return [max(curve[int(i * step):max(int(i * step) + 1, int((i + 1) * step))]) for i in range(points)]


def pick_moments(score, D, n_clips, clip_len, gap, skip_start):
    """Greedy: take the highest-scoring second, build a clip around it, never overlap."""
    lead = int(clip_len * 0.4)                  # 40% before the peak, 60% after
    order = sorted(range(D), key=lambda i: score[i], reverse=True)
    chosen = []
    for p in order:
        if len(chosen) >= n_clips or score[p] <= 0:
            break
        if p < skip_start:
            continue
        s = max(skip_start, min(p - lead, D - clip_len))
        e = min(D, s + clip_len)
        if any(s < ce + gap and e > cs - gap for cs, ce, _ in chosen):
            continue
        chosen.append((s, e, p))
    return chosen


# ---------------------------------------------------------------- main entry
def context_moments(cands, score, utts, n_clips, gap, min_len, max_len, D):
    """Expand candidate peaks to natural speech boundaries (setup -> payoff). Peaks that land in the
    same story are merged into one clip instead of producing two half-stories."""
    from transcript import snap_bounds
    accepted = []          # dicts: start, end, peak, peaks
    for _s, _e, p in cands:          # cands are in score order (best first)
        s, e = snap_bounds(utts, p, min_len, max_len, duration=D)
        merged = False
        for m in accepted:
            if s < m["end"] + gap and e > m["start"] - gap:
                ns, ne = min(s, m["start"]), max(e, m["end"])
                if ne - ns <= max_len:
                    m["start"], m["end"] = ns, ne
                    m["peaks"].append(p)
                merged = True        # either merged or would overlap -> never a duplicate clip
                break
        if not merged and len(accepted) < n_clips:
            accepted.append({"start": s, "end": e, "peak": p, "peaks": [p]})
    return [(m["start"], m["end"], m["peak"], sorted(m["peaks"])) for m in accepted]


def analyze(url, n_clips=5, clip_len=30, gap=10, sources=("heatmap", "chat", "comments"),
            skip_start=0, progress=lambda msg: None, smart=True, min_len=20, max_len=90,
            transcript_cache=None):
    """smart=True: clip edges follow the conversation (captions) so every clip has its full context;
    length varies between min_len and max_len. clip_len is then only the peak-detection window."""
    progress("Reading video info…")
    with yt_dlp.YoutubeDL(BASE_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("is_live"):
        raise RuntimeError("This stream is still LIVE. Engagement data (chat replay, most-replayed) "
                           "is only available after the stream ends.")
    D = int(info.get("duration") or 0)
    if D < clip_len:
        raise RuntimeError("Video is shorter than the requested clip length.")

    curves, used, notes = {}, [], []
    chat_msgs, comment_refs = [], []

    if "heatmap" in sources:
        c = heatmap_curve(info, D)
        if c:
            curves["heatmap"] = c
            used.append("heatmap")
        else:
            notes.append("No 'Most replayed' data (video too new or not enough views).")

    if "chat" in sources:
        if "live_chat" in (info.get("subtitles") or {}):
            c, chat_msgs = load_chat(url, D, progress)
            if c:
                curves["chat"] = c
                used.append("chat")
        else:
            notes.append("No live-chat replay (not a past live stream, or chat replay disabled).")

    if "comments" in sources:
        progress("Reading top comments for timestamps…")
        try:
            c, comment_refs, n_read = load_comments(url, D)
            if c:
                curves["comments"] = c
                used.append("comments")
            else:
                notes.append(f"Read {n_read} comments but none contained timestamps.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Couldn't read comments: {e}")

    if not curves:
        raise RuntimeError("No engagement data found for this video. " + " ".join(notes))

    progress("Scoring moments…")
    width = max(5, clip_len // 2)
    norm = {k: normalise(smooth(v, width)) for k, v in curves.items()}
    total_w = sum(WEIGHTS[k] for k in norm)
    score = [sum(WEIGHTS[k] * norm[k][i] for k in norm) / total_w for i in range(D)]

    utts, words_info = None, None
    if smart:
        progress("Reading captions for context…")
        try:
            from transcript import fetch_words, utterances
            words_info = fetch_words(url, info, cache=transcript_cache)
            if words_info and words_info["words"]:
                utts = utterances(words_info["words"])
            else:
                notes.append("No captions on this video, so clips use the fixed length instead of "
                             "following the conversation.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Couldn't read captions ({e}); using fixed clip length.")

    if utts:
        cands = pick_moments(score, D, max(n_clips * 4, 20), clip_len, 0, skip_start)
        picks = context_moments(cands, score, utts, n_clips, gap, min_len, max_len, D)
    else:
        picks = [(s, e, p, [p]) for s, e, p in pick_moments(score, D, n_clips, clip_len, gap, skip_start)]
    top = max(score) or 1

    moments = []
    for rank, (s, e, p, peaks) in enumerate(picks, 1):
        m = {"rank": rank, "start": s, "end": e, "peak": p,
             "score": round(100 * score[p] / top),
             "signals": {k: round(100 * norm[k][p]) for k in norm}}
        if utts:
            from transcript import text_between
            m["peaks"] = peaks
            m["context"] = "snapped"
            m["transcript"] = text_between(utts, s, e)
        if chat_msgs:
            in_win = [txt for t, txt in chat_msgs if s <= t < e]
            m["chat_count"] = len(in_win)
            m["chat_samples"] = [x for x in in_win if len(x) > 2][:4]
        if comment_refs:
            refs = sorted([r for r in comment_refs if s - 5 <= r[0] < e], key=lambda r: -r[1])
            m["comment_mentions"] = len(refs)
            seen, samples = set(), []
            for r in refs:
                if r[2].lower() not in seen:
                    seen.add(r[2].lower())
                    samples.append(r[2])
                if len(samples) == 3:
                    break
            m["comment_samples"] = samples
        moments.append(m)
    moments.sort(key=lambda m: m["start"])

    from clipper import suggest_hashtags  # local import: clipper doesn't depend on analyzer
    hashtags = suggest_hashtags({"title": info.get("title"), "tags": info.get("tags"),
                                 "categories": info.get("categories"), "channel": info.get("uploader"),
                                 "description": info.get("description")}, moments)

    return {
        "hashtags": hashtags,
        "id": info.get("id"),
        "url": url,
        "clip_len": clip_len,
        "smart": bool(utts),
        "min_len": min_len if utts else None,
        "max_len": max_len if utts else None,
        "caption_lang": words_info["lang"] if utts else None,
        "title": info.get("title"),
        "duration": D,
        "used": used,
        "notes": notes,
        "moments": moments,
        "timeline": [round(v, 3) for v in downsample(normalise(score))],
        "requested": n_clips,
    }
