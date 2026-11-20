"""
Command-line interface for YouTube Clipper - used by the Claude skill (and usable by hand).
Uses exactly the same engine as the web app, so clips are identical.

Progress goes to stderr; the final result is printed to stdout as JSON.

  python cli.py setup                                   # install deps + check ffmpeg
  python cli.py info     URL
  python cli.py analyze  URL --count 10 --length 30 [--gap 15] [--skip-min 0]
                             [--sources heatmap,chat,comments] [--save moments.json]
  python cli.py clip     URL --moments moments.json [--pick 1,2,5]  [--format mp4|mp3] [--quality 720] [--out clips]
  python cli.py clip     URL --ranges "1:10:03-1:10:23,2:01:24-2:01:44"  [...]
  python cli.py auto     URL --count 10 --length 30 [...analyze opts] [...clip opts]   # analyze + clip
  python cli.py hashtags URL [--moments moments.json]
"""
import argparse
import json
import os
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def fail(msg):
    emit({"ok": False, "error": msg}, 1)


# ---------------------------------------------------------------- commands
def cmd_setup(_a):
    req = os.path.join(HERE, "requirements.txt")
    log("Installing Python packages…")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "-r", req],
                       capture_output=True, text=True)
    if r.returncode:
        fail("pip install failed: " + (r.stderr or r.stdout)[-800:])
    import clipper  # noqa: F401  (copies ffmpeg into bin/ on first import)
    import yt_dlp
    emit({"ok": True, "python": sys.version.split()[0], "yt_dlp": yt_dlp.version.__version__,
          "ffmpeg_dir": clipper.FFMPEG})


def _check_url(url):
    from clipper import valid_url
    if not valid_url(url):
        fail(f"Not a YouTube video link: {url}")


def cmd_info(a):
    _check_url(a.url)
    import clipper
    try:
        info = clipper.video_info(a.url)
    except Exception as e:  # noqa: BLE001
        fail(f"Could not read video: {clipper.clean_err(e)}")
    info["description"] = info["description"][:500]
    info["duration_hms"] = clipper.stamp(info["duration"])
    emit({"ok": True, **info})


def _analyze(a):
    import analyzer
    import clipper
    sources = [s.strip() for s in a.sources.split(",") if s.strip()]
    last = [""]

    def prog(m):
        key = m.split("…")[0]
        if key != last[0]:
            log(m)
            last[0] = key

    try:
        res = analyzer.analyze(a.url, a.count, a.length, a.gap, sources, int(a.skip_min * 60), prog)
    except Exception as e:  # noqa: BLE001
        fail(clipper.clean_err(e))
    for m in res["moments"]:
        m["start_hms"], m["end_hms"] = clipper.stamp(m["start"]), clipper.stamp(m["end"])
        m["youtube_link"] = f"https://youtu.be/{res['id']}?t={m['start']}"
    if a.save:
        os.makedirs(os.path.dirname(os.path.abspath(a.save)), exist_ok=True)
        with open(a.save, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        log(f"Saved analysis to {os.path.abspath(a.save)}")
    return res


def _summary(res):
    out = {k: v for k, v in res.items() if k != "timeline"}
    if len(res["moments"]) < res["requested"]:
        out["notes"] = out["notes"] + [
            f"Only {len(res['moments'])} of {res['requested']} non-overlapping moments fit. "
            "Use a shorter clip length or smaller gap for more."]
    return out


def cmd_analyze(a):
    _check_url(a.url)
    emit({"ok": True, **_summary(_analyze(a))})


def _clip(a, moments=None):
    import clipper
    meta = {}
    if getattr(a, "ranges", None):
        try:
            pairs = [r.strip().rsplit("-", 1) for r in a.ranges.split(",") if r.strip()]
            ranges = clipper.validate_ranges([(p[0], p[1]) for p in pairs])
        except (IndexError, ValueError) as e:
            fail(f"Bad --ranges: {e}. Use e.g. \"1:10:03-1:10:23,2:01:24-2:01:44\".")
    else:
        if moments is None:
            if not getattr(a, "moments", None):
                fail("Give --moments <file from analyze --save> or --ranges.")
            with open(a.moments, encoding="utf-8") as fh:
                moments = json.load(fh)["moments"]
        if getattr(a, "pick", None):
            want = {int(x) for x in a.pick.split(",") if x.strip()}
            moments = [m for m in moments if m["rank"] in want]
        if not moments:
            fail("No moments selected.")
        try:
            ranges = clipper.validate_ranges([(m["start"], m["end"]) for m in moments])
        except ValueError as e:
            fail(str(e))
        meta = {(float(m["start"]), float(m["end"])): m for m in moments}

    mode = "mp3" if a.format == "mp3" else "mp4"
    tag = uuid.uuid4().hex[:6]
    out_dir = os.path.abspath(a.out)
    log(f"Creating {len(ranges)} clip(s) into {out_dir} ({PARALLEL} at a time)…")

    def upd(i, item):
        if item["status"] in ("done", "error") or item["status"].startswith("retrying"):
            msg = item.get("file") or item.get("error") or item["status"]
            log(f"  clip {i + 1}/{len(ranges)}: {item['status']} - {msg}")

    res = clipper.make_batch(a.url, ranges, mode, a.quality, out_dir, tag, on_update=upd)
    clips = []
    for i, c in enumerate(res["clips"], 1):
        m = meta.get((float(c["start"]), float(c["end"])), {})
        clips.append({
            "n": i, "rank": m.get("rank"), "score": m.get("score"),
            "start": clipper.stamp(c["start"]), "end": clipper.stamp(c["end"]),
            "seconds": round(c["end"] - c["start"], 1), "status": c["status"],
            "file": os.path.join(out_dir, c["file"]) if c.get("file") else None,
            "error": c.get("error"),
            "chat_samples": m.get("chat_samples"), "comment_samples": m.get("comment_samples"),
        })
    ok = sum(1 for c in clips if c["status"] == "done")
    return {"ok": ok > 0, "created": ok, "failed": len(clips) - ok, "out_dir": out_dir,
            "zip": os.path.join(out_dir, res["zip"]) if res["zip"] else None,
            "format": mode, "quality": a.quality if mode == "mp4" else None, "clips": clips}


def cmd_clip(a):
    _check_url(a.url)
    r = _clip(a)
    emit(r, 0 if r["ok"] else 1)


def cmd_auto(a):
    _check_url(a.url)
    res = _analyze(a)
    if not res["moments"]:
        fail("No moments found.")
    r = _clip(a, res["moments"])
    r["analysis"] = _summary(res)
    emit(r, 0 if r["ok"] else 1)


def cmd_hashtags(a):
    _check_url(a.url)
    import clipper
    try:
        info = clipper.video_info(a.url)
    except Exception as e:  # noqa: BLE001
        fail(clipper.clean_err(e))
    moments = None
    if a.moments:
        with open(a.moments, encoding="utf-8") as fh:
            moments = json.load(fh)["moments"]
    emit({"ok": True, "title": info["title"], "channel": info["channel"],
          "categories": info["categories"], "uploader_tags": info["tags"][:20],
          "hashtags": clipper.suggest_hashtags(info, moments)})


# ---------------------------------------------------------------- argparse
PARALLEL = 2


def main():
    p = argparse.ArgumentParser(prog="cli.py", description="YouTube Clipper CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="install dependencies and check ffmpeg").set_defaults(fn=cmd_setup)

    s = sub.add_parser("info", help="video metadata + which engagement signals exist")
    s.add_argument("url")
    s.set_defaults(fn=cmd_info)

    def analyze_opts(s):
        s.add_argument("--count", type=int, default=10, help="how many clips (1-50)")
        s.add_argument("--length", type=int, default=30, help="seconds per clip (5-600)")
        s.add_argument("--gap", type=int, default=15, help="min seconds between clips")
        s.add_argument("--skip-min", type=float, default=0, help="ignore the first N minutes")
        s.add_argument("--sources", default="heatmap,chat,comments")
        s.add_argument("--save", help="write full analysis JSON here (needed for clip --moments)")

    def clip_opts(s):
        s.add_argument("--format", choices=["mp4", "mp3"], default="mp4")
        s.add_argument("--quality", default="720", choices=["360", "480", "720", "1080", "1440", "2160"])
        s.add_argument("--out", default="clips", help="output folder (default ./clips)")

    s = sub.add_parser("analyze", help="find the most engaging moments")
    s.add_argument("url")
    analyze_opts(s)
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("clip", help="cut clips from saved moments or explicit ranges")
    s.add_argument("url")
    s.add_argument("--moments", help="analysis JSON from `analyze --save`")
    s.add_argument("--pick", help="comma-separated ranks to keep, e.g. 1,2,5")
    s.add_argument("--ranges", help='explicit ranges, e.g. "1:10:03-1:10:23,2:01:24-2:01:44"')
    clip_opts(s)
    s.set_defaults(fn=cmd_clip)

    s = sub.add_parser("auto", help="analyze + clip in one go")
    s.add_argument("url")
    analyze_opts(s)
    clip_opts(s)
    s.set_defaults(fn=cmd_auto)

    s = sub.add_parser("hashtags", help="hashtag candidates from the video + audience")
    s.add_argument("url")
    s.add_argument("--moments")
    s.set_defaults(fn=cmd_hashtags)

    a = p.parse_args()
    if hasattr(a, "count"):
        a.count = max(1, min(50, a.count))
        a.length = max(5, min(600, a.length))
    a.fn(a)


if __name__ == "__main__":
    main()
