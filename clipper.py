"""
Shared clipping engine used by BOTH the web app (app.py) and the CLI / Claude skill (cli.py),
so the output is identical whichever way you use it.
"""
import os
import random
import re
import shutil
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import imageio_ffmpeg
import yt_dlp
from yt_dlp.utils import download_range_func

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_CLIP_SECONDS = 60 * 60
MAX_BATCH = 50
PARALLEL_CLIPS = 2
RETRIES = 4
HEIGHTS = {"360", "480", "720", "1080", "1440", "2160"}

YT_RE = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?"
    r"(youtube\.com/(watch\?.*v=|shorts/|live/|embed/)|youtu\.be/)"
    r"[\w-]{11}"
)


# ---------------------------------------------------------------- ffmpeg setup
def _ffmpeg_dir():
    """yt-dlp needs a binary literally named ffmpeg(.exe); imageio's is versioned, so copy it."""
    on_path = shutil.which("ffmpeg")
    if on_path:
        return os.path.dirname(on_path)
    bin_dir = os.path.join(BASE_DIR, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    target = os.path.join(bin_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not os.path.exists(target):
        shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), target)
        if os.name != "nt":
            os.chmod(target, 0o755)
    return bin_dir


FFMPEG = _ffmpeg_dir()
# yt-dlp's section-download check only looks on PATH, so expose it there too.
os.environ["PATH"] = FFMPEG + os.pathsep + os.environ.get("PATH", "")


# ---------------------------------------------------------------- helpers
def parse_time(value):
    """Accept 90, '90.5', '1:30', '01:01:30' -> seconds."""
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError("negative time")
        return float(value)
    value = str(value).strip()
    if not value:
        raise ValueError("empty time")
    parts = value.split(":")
    if len(parts) > 3:
        raise ValueError(f"bad time: {value}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + float(p)
    if seconds < 0:
        raise ValueError("negative time")
    return seconds


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def stamp(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def valid_url(url):
    return bool(YT_RE.match((url or "").strip()))


def clean_err(e):
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")


def video_info(url):
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        data = ydl.extract_info(url, download=False)
    return {
        "id": data.get("id"), "title": data.get("title"), "channel": data.get("uploader"),
        "duration": data.get("duration") or 0, "is_live": bool(data.get("is_live")),
        "was_live": data.get("live_status") == "was_live",
        "has_heatmap": bool(data.get("heatmap")),
        "has_chat": "live_chat" in (data.get("subtitles") or {}),
        "comment_count": data.get("comment_count"),
        "view_count": data.get("view_count"),
        "tags": data.get("tags") or [], "categories": data.get("categories") or [],
        "description": data.get("description") or "",
        "upload_date": data.get("upload_date"),
        "timestamp": data.get("release_timestamp") or data.get("timestamp"),
    }


def validate_ranges(ranges):
    """[(start,end)...] -> sorted list; raises ValueError on invalid / overlapping ranges."""
    clips = []
    for s, e in ranges:
        s, e = parse_time(s), parse_time(e)
        if e <= s:
            raise ValueError(f"End must be after start ({stamp(s)} - {stamp(e)}).")
        if e - s > MAX_CLIP_SECONDS:
            raise ValueError("Clips are limited to 1 hour.")
        clips.append((s, e))
    if not clips:
        raise ValueError("No clips given.")
    if len(clips) > MAX_BATCH:
        raise ValueError(f"Max {MAX_BATCH} clips per batch.")
    clips.sort()
    for (_s1, e1), (s2, _e2) in zip(clips, clips[1:]):
        if s2 < e1:
            raise ValueError(f"Clips overlap around {stamp(s2)} - adjust the times.")
    return clips


# ---------------------------------------------------------------- clipping core
def _outputs(out_dir, prefix):
    return sorted(f for f in os.listdir(out_dir)
                  if f.startswith(prefix + "_") and not f.endswith((".part", ".ytdl", ".zip", ".temp")))


def _cleanup(out_dir, prefix):
    for f in os.listdir(out_dir):
        if f.startswith(prefix + "_"):
            try:
                os.remove(os.path.join(out_dir, f))
            except OSError:
                pass


def make_clip(url, start, end, mode, height, prefix, out_dir, on_progress=None):
    """Download only [start, end] of the video into out_dir. Returns the output file name."""
    os.makedirs(out_dir, exist_ok=True)
    height = str(height) if str(height) in HEIGHTS else "720"

    def hook(d):
        if not on_progress:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = round(d.get("downloaded_bytes", 0) * 100 / total) if total else None
            on_progress("downloading", pct)
        elif d.get("status") == "finished":
            on_progress("processing", None)

    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
        "ffmpeg_location": FFMPEG,
        "outtmpl": os.path.join(out_dir, f"{prefix}_%(id)s_{fmt_time(start)}-{fmt_time(end)}.%(ext)s"),
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "progress_hooks": [hook],
    }
    if mode == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                   "preferredquality": "192"}]
    else:
        h = int(height)
        if h > 1080:   # YouTube only offers 1440p/4K as VP9/AV1, so don't prefer the mp4 (H.264) track
            opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]/b"
        else:
            opts["format"] = f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b"
        opts["merge_output_format"] = "mp4"

    # YouTube's CDN sometimes answers 503/403 for a stream URL. Each retry re-extracts
    # (fresh signed URLs, often a different server); later attempts loosen the format choice.
    last_err = None
    for attempt in range(RETRIES):
        if attempt:
            _cleanup(out_dir, prefix)
            if on_progress:
                on_progress(f"retrying ({attempt}/{RETRIES - 1})", None)
            time.sleep(2 + 3 * attempt + random.random() * 2)
            if mode != "mp3" and attempt >= 2:
                opts["format"] = f"b[height<={height}]/bv*+ba/b"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
            produced = _outputs(out_dir, prefix)
            if produced:
                return produced[-1]
            last_err = RuntimeError("No output file was produced.")
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            if not re.search(r"exited with code|HTTP Error|5\d\d|403|timed out|reset", str(e), re.I):
                break  # not transient (private video, bad URL...) -> don't retry
    _cleanup(out_dir, prefix)
    raise last_err


def make_batch(url, ranges, mode, height, out_dir, tag, items=None, on_update=None):
    """
    Cut many clips (PARALLEL_CLIPS at a time) and zip them.
    `items` (optional) is a list of dicts that gets live status updates (used by the web UI).
    Returns {"clips": [...], "zip": name|None, "out_dir": out_dir}.
    """
    os.makedirs(out_dir, exist_ok=True)
    if items is None:
        items = [{"start": s, "end": e, "status": "queued", "progress": 0, "file": None, "error": None}
                 for s, e in ranges]

    def one(i):
        item = items[i]

        def prog(status, pct):
            item["status"] = status
            if pct is not None:
                item["progress"] = pct
            if on_update:
                on_update(i, item)

        try:
            prog("starting", None)
            item["file"] = make_clip(url, item["start"], item["end"], mode, height,
                                     f"{tag}_{i + 1:02d}", out_dir, prog)
            item.update(status="done", progress=100)
        except Exception as e:  # noqa: BLE001
            item.update(status="error", error=clean_err(e))
        if on_update:
            on_update(i, item)

    with ThreadPoolExecutor(max_workers=PARALLEL_CLIPS) as pool:
        list(pool.map(one, range(len(items))))

    done = [c["file"] for c in items if c.get("file")]
    zip_name = None
    if done:
        zip_name = f"{tag}_clips_{len(done)}.zip"
        with zipfile.ZipFile(os.path.join(out_dir, zip_name), "w", zipfile.ZIP_STORED) as z:
            for f in done:
                z.write(os.path.join(out_dir, f), arcname=f)
    return {"clips": items, "zip": zip_name, "out_dir": os.path.abspath(out_dir)}


# ---------------------------------------------------------------- hashtags
STOP = set("""a an the and or but if then so of to in on at by for with from up down out over under
is are was were be been being this that these those it its as into about after before than too very
can will just not no yes you your we our they their he she his her i me my mine what when where who
why how all any both each few more most other some such only own same s t don now live stream full
video official replay vod part new watch www http https com youtube lol lmao chat lets let get got""".split())
FILLER = set("""during return returns experiences experience happens happened goes going gets
made make makes first last best ever really here there today tonight episode ep watch full highlights
moment moments reaction reacts reacting versus""".split())
GENERIC =["#Shorts", "#Clips", "#Highlights", "#Viral", "#Trending", "#YouTubeShorts"]


def _tagify(text):
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return None
    tag = "".join(w if w.isupper() and len(w) <= 5 else w.capitalize() for w in words)
    return "#" + tag if 2 < len(tag) <= 30 else None


def suggest_hashtags(info, moments=None, limit=25):
    """
    Hashtag CANDIDATES built from the video itself (uploader tags, description hashtags,
    title keywords, category, channel) and from what the audience said in chat/comments
    at the chosen moments. Claude can then add currently-trending tags on top (web search).
    """
    seen, out = set(), {"from_video": [], "from_title": [], "from_audience": [], "generic": []}

    def add(bucket, tag):
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out[bucket].append(tag)

    # title: acronyms / names with digits first, then adjacent proper-noun pairs, then a few keywords
    raw = re.findall(r"[A-Za-z][A-Za-z0-9]+", info.get("title") or "")
    words = [w for w in raw if w.lower() not in STOP and w.lower() not in FILLER and len(w) > 2]
    for w in words:
        if (w.isupper() and len(w) <= 6) or any(ch.isdigit() for ch in w):
            add("from_title", "#" + w)
    for a, b in zip(raw, raw[1:]):
        if a in words and b in words and a[0].isupper() and b[0].isupper():
            add("from_title", _tagify(f"{a} {b}"))
    for w in sorted(words, key=len, reverse=True)[:3]:
        add("from_title", _tagify(w))

    for h in re.findall(r"#(\w{3,30})", info.get("description") or ""):
        add("from_video", "#" + h)
    for t in (info.get("tags") or [])[:8]:
        add("from_video", _tagify(t))
    if info.get("channel"):
        add("from_video", _tagify(info["channel"]))

    if moments:
        words = Counter()
        for m in moments:
            for txt in (m.get("chat_samples") or []) + (m.get("comment_samples") or []):
                for w in re.findall(r"[A-Za-z]{4,}", txt):
                    if w.lower() not in STOP:
                        words[w.lower()] += 1
        for w, n in words.most_common(10):
            if n >= 2:
                add("from_audience", _tagify(w))

    for g in GENERIC:
        add("generic", g)

    flat = [t for k in ("from_title", "from_video", "from_audience", "generic") for t in out[k]]
    out["all"] = flat[:limit]
    return out
