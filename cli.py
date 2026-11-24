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
  python cli.py context  URL --moments moments.json [--pick 1,3] [--before 90 --after 60]
  python cli.py frames   URL --start 5:18:00 --end 5:20:00 [--out dir]
  python cli.py reel     URL --plan plan.json [--quality 1440] [--out reels]
  python cli.py dub-script URL --plan plan.json --lang hi [--voice ..] [--lipsync none|sync]   # then translate + reel

  python cli.py connect  youtube --client-secret client_secret.json  |  connect instagram --token TOKEN
  python cli.py accounts [--disconnect youtube|instagram]       # disconnect also revokes the token
  python cli.py rights   [--accept|--withdraw]                  # confirm you own / may clip the videos
  python cli.py forget   [--outputs clips reels]                # revoke access + delete all local data
  python cli.py trends   --keywords "gta 6,mythpat" [--today] [--ig-check 5]
  python cli.py best-times [--platforms youtube,instagram] [--tz Asia/Kolkata] [--hot]
  python cli.py plan-posts --plan plan.json --reels reels --url URL [--moments m.json] --save posts.json
  python cli.py publish  --posts posts.json [--only 1,3] [--now] [--dry-run]
  python cli.py queue | post-due | runner --loop|--install|--uninstall

analyze follows the conversation by default (captions): each clip starts before the setup and ends
after the payoff, 20-90 s (--min-len/--max-len), and peaks from the same story are merged.
Use --fixed for exact --length clips.
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


def _need_rights():
    """Downloading needs the user's one-time confirmation that they own the video or have permission."""
    import compliance
    st = compliance.status()
    if not st["accepted"]:
        emit({"ok": False, "error": "rights_not_confirmed", "notice": st["notice"],
              "next": "Show the notice to the user. Only if they confirm, run `python cli.py rights --accept`."}, 1)


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

    cache = None
    if a.save:
        cache = os.path.join(os.path.dirname(os.path.abspath(a.save)), "transcript.json")
    try:
        res = analyzer.analyze(a.url, a.count, a.length, a.gap, sources, int(a.skip_min * 60), prog,
                               smart=not a.fixed, min_len=a.min_len, max_len=a.max_len,
                               transcript_cache=cache)
    except Exception as e:  # noqa: BLE001
        fail(clipper.clean_err(e))
    for m in res["moments"]:
        m["start_hms"], m["end_hms"] = clipper.stamp(m["start"]), clipper.stamp(m["end"])
        m["seconds"] = round(m["end"] - m["start"], 1)
        m["youtube_link"] = f"https://youtu.be/{res['id']}?t={int(m['start'])}"
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
    _need_rights()
    r = _clip(a)
    emit(r, 0 if r["ok"] else 1)


def cmd_auto(a):
    _check_url(a.url)
    _need_rights()
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


def _hms(t):
    t = max(0.0, float(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"


def _words(url, cache):
    import transcript
    try:
        return transcript.fetch_words(url, cache=cache)
    except Exception as e:  # noqa: BLE001
        log(f"Couldn't read captions: {e}")
        return None


def cmd_context(a):
    """Timed transcript around each moment, so Claude can judge setup/payoff and set exact edges."""
    _check_url(a.url)
    import transcript
    with open(a.moments, encoding="utf-8") as fh:
        res = json.load(fh)
    cache = os.path.join(os.path.dirname(os.path.abspath(a.moments)), "transcript.json")
    tw = _words(a.url, cache)
    if not tw or not tw["words"]:
        fail("This video has no captions, so the conversation can't be read. Judge context from "
             "comment/chat samples and `frames` instead.")
    utts = transcript.utterances(tw["words"])
    want = {int(x) for x in a.pick.split(",")} if a.pick else None
    out = []
    for m in res["moments"]:
        if want and m["rank"] not in want:
            continue
        lo, hi = m["start"] - a.before, m["end"] + a.after
        lines = []
        for u in transcript.lines_between(utts, lo, hi):
            mark = ">" if m["start"] <= u["start"] < m["end"] else " "
            if any(u["start"] <= p < u["end"] + 1 for p in m.get("peaks", [m["peak"]])):
                mark = "*"
            gap = f" (pause {u['pause_before']:.1f}s)" if 1.5 <= u["pause_before"] < 99 else ""
            lines.append(f"{mark} {_hms(u['start'])}-{_hms(u['end'])}{gap}  {u['text']}")
        out.append({"rank": m["rank"], "suggested": [_hms(m["start"]), _hms(m["end"])],
                    "seconds": round(m["end"] - m["start"], 1),
                    "peaks": [_hms(p) for p in m.get("peaks", [m["peak"]])],
                    "comment_samples": m.get("comment_samples"), "chat_samples": m.get("chat_samples"),
                    "lines": lines})
    emit({"ok": True, "lang": tw["lang"], "auto_captions": tw.get("auto"),
          "legend": "'>' inside suggested clip, '*' engagement peak, (pause) = silence before the line",
          "moments": out})


def cmd_frames(a):
    """Contact sheet (grid of frames with timestamps) for a time range - to see the on-screen layout."""
    _check_url(a.url)
    _need_rights()
    import clipper
    import reel
    s, e = clipper.parse_time(a.start), clipper.parse_time(a.end)
    out_dir = os.path.abspath(a.out)
    tag = uuid.uuid4().hex[:6]
    try:
        f = clipper.make_clip(a.url, s, e, "mp4", "360", tag, out_dir)
        sheet = os.path.join(out_dir, f"frames_{clipper.fmt_time(s)}-{clipper.fmt_time(e)}.jpg")
        reel.contact_sheet(os.path.join(out_dir, f), sheet, offset=s)
        os.remove(os.path.join(out_dir, f))
    except Exception as ex:  # noqa: BLE001
        fail(clipper.clean_err(ex))
    emit({"ok": True, "image": sheet, "range": [clipper.stamp(s), clipper.stamp(e)]})


def cmd_reel(a):
    """Download each planned range at high quality and render finished vertical reels + a ZIP."""
    _check_url(a.url)
    _need_rights()
    import compliance
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    import clipper
    import reel
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    specs = plan["reels"]
    try:
        clipper.validate_ranges([(r["start"], r["end"]) for r in specs])
    except ValueError as e:
        fail(str(e))
    out_dir = os.path.abspath(a.out)
    src_dir = os.path.join(out_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    need_words = any(r.get("captions") is True for r in specs)
    words = None
    if need_words:
        tw = _words(a.url, a.transcript or os.path.join(out_dir, "transcript.json"))
        words = tw["words"] if tw else None
        if not words:
            log("No captions available - reels will be rendered without subtitles.")
    tag = uuid.uuid4().hex[:6]

    def one(i):
        r = specs[i]
        name = f"{i + 1:02d}_{reel.slug(r.get('title', 'reel'))}.mp4"
        s, e = clipper.parse_time(r["start"]), clipper.parse_time(r["end"])
        try:
            log(f"  reel {i + 1}/{len(specs)}: downloading {clipper.stamp(s)}-{clipper.stamp(e)} at {a.quality}p…")
            f = clipper.make_clip(a.url, s, e, "mp4", a.quality, f"{tag}{i:02d}", src_dir)
            src = os.path.join(src_dir, f)
            rr, dubinfo = r, None
            if r.get("dub") and not a.no_dub:
                import dub
                import lipsync
                log(f"  reel {i + 1}/{len(specs)}: dubbing to {r['dub'].get('lang', '?')}…")
                dsrc = src[:-4] + f".dub-{r['dub'].get('lang', 'x')}.mp4"
                dubinfo = dub.dub_clip(src, dsrc, r, log=log)
                lip = r["dub"].get("lipsync", "none")
                if lip not in (None, "", "none"):
                    log(f"  reel {i + 1}/{len(specs)}: lip-sync ({lip})…")
                    mixed = os.path.join(os.path.dirname(dubinfo["voice_track"]), "dub_mix.wav")
                    dsrc = lipsync.apply(lip, dsrc, dubinfo["voice_track"], mixed, dsrc[:-4] + ".lips.mp4",
                                         dub.FFMPEG_EXE, log=log)
                src = dsrc
                rr = {**r, "ai_label": compliance.ai_label(r)}   # visible AI disclosure on the reel
                if not isinstance(r.get("captions"), list) and r.get("captions", True) is not False:
                    rr["captions"] = dub.caption_lines(r)
            log(f"  reel {i + 1}/{len(specs)}: rendering…")
            info = reel.render(src, os.path.join(out_dir, name), rr, words, plan.get("credit", ""), log=log)
            if dubinfo:
                info["dub"] = {k: dubinfo[k] for k in ("voice", "lines", "background")}
                info["synthetic"] = True
            log(f"  reel {i + 1}/{len(specs)}: done ({info['seconds']} s)")
            return {"n": i + 1, "status": "done", "title": r.get("title"), "start": clipper.stamp(s),
                    "end": clipper.stamp(e), **info}
        except Exception as ex:  # noqa: BLE001
            log(f"  reel {i + 1}/{len(specs)}: FAILED - {clipper.clean_err(ex)[:300]}")
            return {"n": i + 1, "status": "error", "title": r.get("title"), "error": clipper.clean_err(ex)[:600]}

    with ThreadPoolExecutor(max(1, min(4, a.parallel))) as ex:
        results = list(ex.map(one, range(len(specs))))
    done = [r for r in results if r["status"] == "done"]
    zpath = None
    if done:
        zpath = os.path.join(out_dir, f"reels_{tag}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
            for r in done:
                z.write(r["file"], os.path.basename(r["file"]))
    emit({"ok": bool(done), "created": len(done), "failed": len(results) - len(done),
          "out_dir": out_dir, "zip": zpath, "reels": results}, 0 if done else 1)


def cmd_dub_script(a):
    """Add a dub skeleton to every reel in plan.json: the original lines with times, ready to translate."""
    import dub
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    tw = _words(a.url, a.transcript or os.path.join(os.path.dirname(os.path.abspath(a.plan)), "transcript.json"))
    if not tw:
        fail("No captions for this video, so there is nothing to translate.")
    out = []
    for i, r in enumerate(plan["reels"], 1):
        s, e = clipper_time(r["start"]), clipper_time(r["end"])
        lines = dub.script_lines(tw["words"], s, e, r.get("cuts"))
        r["dub"] = {"lang": a.lang, "voice": a.voice or dub.voice_for(a.lang, a.gender), "rate": "+28%",
                    "lipsync": a.lipsync, "lines": [[x[0], x[1], "", "", x[2]] for x in lines]}
        out.append({"reel": i, "title": r.get("title"), "lines": len(lines)})
    with open(a.plan, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    emit({"ok": True, "plan": os.path.abspath(a.plan), "source_lang": tw.get("lang"), "target": a.lang,
          "reels": out, "next": "Fill each line: [start, end, spoken text in the target script, "
                                "caption text (optional, e.g. Roman script), original]. Then run `reel`."})


def clipper_time(t):
    import clipper
    return clipper.parse_time(str(t))


def cmd_voices(a):
    import dub
    emit({"ok": True, "defaults": dub.VOICES,
          "note": "Any edge-tts voice works: run `python -m edge_tts --list-voices` for all of them."})



# ---------------------------------------------------------------- social: accounts, trends, timing, publishing
def _pub():
    import publish
    return publish


def cmd_connect(a):
    pub = _pub()
    try:
        if a.platform == "youtube":
            ch = pub.yt_connect(a.client_secret, open_browser=not a.no_browser, log=log)
            emit({"ok": True, "platform": "youtube", "channel": ch})
        if not a.token:
            fail("Instagram needs --token (a long-lived access token with instagram_content_publish "
                 "or instagram_business_content_publish permission). See README: 'Connect Instagram'.")
        emit({"ok": True, "platform": "instagram",
              "account": pub.ig_connect(a.token, a.ig_user_id, a.host, a.api_version)})
    except pub.PublishError as e:
        fail(str(e))


def cmd_accounts(a):
    pub = _pub()
    revoked = None
    if a.disconnect:
        revoked = pub.disconnect(a.disconnect)
    emit({"ok": True, **pub.accounts(), **({"revoked": revoked} if revoked is not None else {})})


def cmd_rights(a):
    """Show (or record) the user's confirmation that they own the videos they clip or have permission."""
    import compliance
    if a.accept and a.withdraw:
        fail("Use --accept or --withdraw, not both.")
    st = compliance.accept() if a.accept else compliance.revoke() if a.withdraw else compliance.status()
    emit({"ok": True, **st, "terms": os.path.join(HERE, "TERMS.md"), "privacy": os.path.join(HERE, "PRIVACY.md")})


def cmd_forget(a):
    """Revoke Google/Instagram access and delete every file this tool keeps about the user."""
    import shutil
    pub = _pub()
    revoked = {plat: pub.disconnect(plat) for plat in ("youtube", "instagram")}
    removed = []
    for d in [pub.HOME] + [os.path.abspath(x) for x in (a.outputs or [])]:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d)
    emit({"ok": True, "revoked": revoked, "deleted": removed,
          "note": "If the app is still listed at https://myaccount.google.com/permissions, remove it there too."})


def _keywords(a, info=None):
    if getattr(a, "keywords", None):
        return [k.strip() for k in a.keywords.split(",") if k.strip()]
    kw = []
    if info:
        kw.append(info.get("channel") or "")
        kw += [t for t in (info.get("tags") or [])[:3]]
    return [k for k in kw if k]


def cmd_trends(a):
    import trends
    if not a.keywords:
        fail('Give topic keywords, e.g. --keywords "gta 6,mythpat"')
    res = trends.trending_tags(_keywords(a), today=a.today, ig_check=a.ig_check, log=log)
    res["suggested"] = {"instagram": trends.pick_tags(res, platform="instagram"),
                        "youtube": trends.pick_tags(res, platform="youtube")}
    if a.save:
        with open(a.save, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
    emit({"ok": True, **res})


def _history_and_online(platforms):
    pub = _pub()
    hist, online = {}, None
    acc = pub.accounts()
    if "youtube" in platforms and acc["youtube"]["connected"]:
        try:
            hist["youtube"] = pub.yt_history()
        except Exception as e:  # noqa: BLE001
            log(f"YouTube history unavailable: {e}")
    if "instagram" in platforms and acc["instagram"]["connected"]:
        try:
            hist["instagram"] = pub.ig_history()
            online = pub.ig_online_followers()
        except Exception as e:  # noqa: BLE001
            log(f"Instagram history unavailable: {e}")
    return hist, online


def _start(a):
    import publish
    return publish.parse_when(a.start) if getattr(a, "start", None) else None


def cmd_best_times(a):
    import timing
    plats = [p.strip() for p in a.platforms.split(",")]
    hist, online = _history_and_online(plats)
    zone = timing.tz(a.tz)
    out = {}
    for p in plats:
        aud = timing.Audience(p, zone, a.style or "general", online if p == "instagram" else None, hist.get(p))
        out[p] = {"based_on": aud.sources,
                  "weekday_peak_hours": aud.peak_hours(False), "weekend_peak_hours": aud.peak_hours(True),
                  "next_best": [{"local": timing._fmt(t), "at": t.isoformat(), "score": round(s, 1),
                                 "why": timing.explain(aud, t)}
                                for s, t in timing.best_slots(aud, _start(a), a.days, hot=a.hot, n=a.n)]}
    emit({"ok": True, "timezone": a.tz, **out})


def cmd_plan_posts(a):
    """Build posts.json: per reel a priority, captions/hashtags per platform and the best time to post."""
    import time as _t
    import clipper
    import timing
    import trends
    import reel as reelmod
    import compliance
    plats = [p.strip() for p in a.platforms.split(",")]
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    files = sorted(f for f in os.listdir(a.reels) if f.lower().endswith(".mp4"))
    if len(files) < len(plan["reels"]):
        fail(f"{a.reels} has {len(files)} reels but the plan has {len(plan['reels'])}.")
    info, age = None, None
    if a.url:
        try:
            info = clipper.video_info(a.url)
            if info.get("timestamp"):
                age = (_t.time() - info["timestamp"]) / 86400
        except Exception as e:  # noqa: BLE001
            log(f"Couldn't read the source video: {e}")
    kws = _keywords(a, info)
    if a.trends and os.path.isfile(a.trends):
        with open(a.trends, encoding="utf-8") as fh:
            trend = json.load(fh)
    else:
        log("Finding this week's trending hashtags…")
        trend = trends.trending_tags(kws, log=log) if kws else {}
    moments = []
    if a.moments and os.path.isfile(a.moments):
        with open(a.moments, encoding="utf-8") as fh:
            moments = json.load(fh).get("moments", [])
    own = []
    if info:  # the creator's own hashtags + channel name; audience/generic words are too noisy for posting
        h = clipper.suggest_hashtags(info, moments)
        chan = (info.get("channel") or "").replace(" ", "").lower()
        own = h.get("from_video", [])[:4] + [t for t in h.get("from_title", []) if t.lstrip("#").lower() == chan]
    style = a.style or ("gaming" if info and "Gaming" in (info.get("categories") or []) else "general")

    rows = []
    for i, spec in enumerate(plan["reels"]):
        path = os.path.join(a.reels, files[i])
        secs = reelmod._probe(path)[3]
        st, en = clipper.parse_time(str(spec["start"])), clipper.parse_time(str(spec["end"]))
        ms = [m["score"] / 100 for m in moments
              if m["start"] - 5 <= st <= m["end"] + 5 or any(st <= pk <= en for pk in m.get("peaks", []))]
        an = timing.analyze_reel({**spec, "seconds": secs}, max(ms) if ms else None, trend, age, kws)
        rows.append({"name": files[i], "file": os.path.abspath(path), "seconds": round(secs, 1),
                     "title": spec.get("title", ""), "subtitle": spec.get("subtitle", ""),
                     "ai_line": compliance.ai_post_line(spec), **an})
    hist, online = _history_and_online(plats)
    sched = timing.schedule(rows, plats, a.tz, _start(a), a.gap, style, online, hist, a.days)
    credit = plan.get("credit", "")
    src = f"\nFull stream: {a.url}" if a.url else ""
    ig_tags = trends.pick_tags(trend, own, "instagram")
    yt_tags = trends.pick_tags(trend, own, "youtube")
    posts = []
    for r in sched["reels"]:
        body = r["title"] + (f"\n{r['subtitle']}" if r["subtitle"] else "")
        ai = r.get("ai_line", "")
        if ai:
            body += f"\n\n{ai}"
        post = {k: r[k] for k in ("name", "file", "seconds", "title", "priority", "hot", "reasons")}
        post["synthetic"] = bool(ai)
        if "youtube" in r["slots"]:
            post["youtube"] = {"title": f"{r['title']} {' '.join(yt_tags[:2])}".strip(),
                               "description": f"{body}\n\n🎥 Credit: {credit}{src}\n\n{' '.join(yt_tags)}",
                               "tags": list(dict.fromkeys(t.lstrip("#") for t in yt_tags + own)),
                               "synthetic": bool(ai), **r["slots"]["youtube"]}
        if "instagram" in r["slots"]:
            post["instagram"] = {"caption": f"{body}\n\n🎥 {credit}\n\n{' '.join(ig_tags)}",
                                 **r["slots"]["instagram"]}
        posts.append(post)
    out = {"ok": True, "timezone": a.tz, "style": style, "keywords": kws, "based_on": sched["based_on"],
           "order": sched["order"], "trending": [t["tag"] for t in trend.get("topic", [])[:12]],
           "posts": posts}
    if a.save:
        with open(a.save, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        out["saved"] = os.path.abspath(a.save)
    emit(out)


def cmd_publish(a):
    """Publish posts.json. YouTube: uploaded now (scheduled with publishAt). Instagram: queued for post-due."""
    pub = _pub()
    with open(a.posts, encoding="utf-8") as fh:
        doc = json.load(fh)
    posts = doc["posts"]
    pick = {int(x) for x in a.only.split(",")} if a.only else None
    plats = [p.strip() for p in a.platforms.split(",")]
    acc = pub.accounts()
    missing = [p for p in plats if not acc[p]["connected"] and any(p in x for x in posts)]
    if missing and not a.dry_run:
        fail("Not connected: " + ", ".join(missing) + ". Run `python cli.py connect <platform>` first.")
    now = pub.datetime.now(pub.timezone.utc)
    results, queued = [], []
    for i, p in enumerate(posts, 1):
        if pick and i not in pick:
            continue
        for plat in plats:
            if plat not in p:
                continue
            spec = p[plat]
            at = None if a.now else spec.get("at")
            if a.dry_run:
                results.append({"reel": p["name"], "platform": plat,
                                "when": spec.get("local") if at else "now", "dry_run": True})
                continue
            try:
                if plat == "youtube":
                    log(f"Uploading {p['name']} to YouTube…")
                    r = pub.yt_upload(p["file"], spec["title"], spec.get("description", ""), spec.get("tags"),
                                      publish_at=at, log=log,
                                      synthetic=bool(spec.get("synthetic") or p.get("synthetic")))
                    spec["result"] = r
                    results.append({"reel": p["name"], **r})
                elif at and pub.parse_when(at) > now:
                    queued.append({"platform": plat, "file": p["file"], "at": at, "caption": spec["caption"],
                                   "name": p["name"], "local": spec.get("local")})
                    results.append({"reel": p["name"], "platform": plat, "queued_for": spec.get("local")})
                else:
                    log(f"Posting {p['name']} to Instagram…")
                    r = pub.ig_upload(p["file"], spec["caption"], log=log)
                    spec["result"] = r
                    results.append({"reel": p["name"], **r})
            except pub.PublishError as e:
                results.append({"reel": p["name"], "platform": plat, "error": str(e)})
    if queued:
        pub.queue_add(queued)
    if not a.dry_run:
        with open(a.posts, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
    note = None
    if queued:
        note = ("Instagram posts are queued. They go out when `python cli.py post-due` runs: keep "
                "`python cli.py runner --loop` open, or install the timer with `python cli.py runner --install`.")
    emit({"ok": not any("error" in r for r in results), "results": results, "queued": len(queued),
          "note": note})


def cmd_queue(a):
    pub = _pub()
    q = pub.queue_cancel(a.cancel.split(",")) if a.cancel else pub.queue_load()
    emit({"ok": True, "queue": [{k: j.get(k) for k in ("id", "platform", "name", "local", "at", "status", "error",
                                                       "result")}
                                for j in q if a.all or j["status"] == "pending"]})


def cmd_post_due(_a):
    pub = _pub()
    done = pub.post_due(log=log)
    emit({"ok": all(j["status"] != "failed" for j in done),
          "posted": [{k: j.get(k) for k in ("id", "platform", "name", "status", "result", "error")} for j in done]})


TASK = "YouTubeClipperPoster"


def cmd_runner(a):
    if a.install:
        py = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(py):
            py = sys.executable
        tr = f'"{py}" "{os.path.join(HERE, "cli.py")}" post-due'
        r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(a.every), "/TN", TASK,
                            "/TR", tr], capture_output=True, text=True)
        emit({"ok": r.returncode == 0, "task": TASK, "every_min": a.every, "output": (r.stdout or r.stderr).strip()})
    if a.uninstall:
        r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK], capture_output=True, text=True)
        emit({"ok": r.returncode == 0, "output": (r.stdout or r.stderr).strip()})
    import time as _t
    pub = _pub()
    log(f"Posting queued reels when due (checking every {a.every} min). Ctrl+C to stop.")
    while any(j["status"] == "pending" for j in pub.queue_load()):
        pub.post_due(log=log)
        _t.sleep(a.every * 60)
    emit({"ok": True, "message": "Queue empty."})


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
        s.add_argument("--min-len", type=int, default=20, help="shortest clip when following context")
        s.add_argument("--max-len", type=int, default=90, help="longest clip when following context")
        s.add_argument("--fixed", action="store_true",
                       help="exact --length clips instead of following the conversation")

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

    s = sub.add_parser("context", help="timed transcript around each moment (for exact, in-context edges)")
    s.add_argument("url")
    s.add_argument("--moments", required=True)
    s.add_argument("--pick", help="only these ranks")
    s.add_argument("--before", type=float, default=90, help="seconds of transcript before each moment")
    s.add_argument("--after", type=float, default=60, help="seconds of transcript after each moment")
    s.set_defaults(fn=cmd_context)

    s = sub.add_parser("frames", help="contact sheet of frames for a range (see the screen layout)")
    s.add_argument("url")
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--out", default="clips")
    s.set_defaults(fn=cmd_frames)

    s = sub.add_parser("reel", help="render vertical 9:16 reels from a plan JSON")
    s.add_argument("url")
    s.add_argument("--plan", required=True, help="plan JSON (see reel.py for the format)")
    s.add_argument("--quality", default="1440", choices=["720", "1080", "1440", "2160"])
    s.add_argument("--out", default="reels")
    s.add_argument("--transcript", help="transcript.json cache from analyze (optional)")
    s.add_argument("--no-dub", action="store_true", help="ignore dub sections (original audio)")
    s.add_argument("--parallel", type=int, default=PARALLEL, help="reels rendered at once (1-4)")
    s.set_defaults(fn=cmd_reel)

    s = sub.add_parser("dub-script", help="add translatable lines (with times) to every reel in plan.json")
    s.add_argument("url")
    s.add_argument("--plan", required=True)
    s.add_argument("--lang", required=True, help="target language: hi, en, ta, te, bn, mr, es, ...")
    s.add_argument("--voice", help="edge-tts voice (default: a natural voice for --lang)")
    s.add_argument("--gender", choices=["male", "female"], default="male")
    s.add_argument("--lipsync", choices=["none", "sync"], default="none", help="sync = sync.so cloud (API key)")
    s.add_argument("--transcript")
    s.set_defaults(fn=cmd_dub_script)

    sub.add_parser("voices", help="default dubbing voices per language").set_defaults(fn=cmd_voices)

    s = sub.add_parser("hashtags", help="hashtag candidates from the video + audience")
    s.add_argument("url")
    s.add_argument("--moments")
    s.set_defaults(fn=cmd_hashtags)

    s = sub.add_parser("connect", help="connect your YouTube channel or Instagram account")
    s.add_argument("platform", choices=["youtube", "instagram"])
    s.add_argument("--client-secret", help="YouTube: OAuth client JSON (Desktop app) from Google Cloud")
    s.add_argument("--no-browser", action="store_true", help="YouTube: print the sign-in link instead")
    s.add_argument("--token", help="Instagram: long-lived access token")
    s.add_argument("--ig-user-id", help="Instagram: account id (found automatically if omitted)")
    s.add_argument("--host", choices=["graph.facebook.com", "graph.instagram.com"],
                   help="Instagram API host (auto: IG... tokens use graph.instagram.com)")
    s.add_argument("--api-version", help="Graph API version, e.g. v25.0")
    s.set_defaults(fn=cmd_connect)

    s = sub.add_parser("accounts", help="show connected accounts")
    s.add_argument("--disconnect", choices=["youtube", "instagram"],
                   help="revoke access with the platform and delete the stored token")
    s.set_defaults(fn=cmd_accounts)

    s = sub.add_parser("rights", help="show or record the rights confirmation needed before clipping")
    s.add_argument("--accept", action="store_true", help="the user confirms they own the video or have permission")
    s.add_argument("--withdraw", action="store_true")
    s.set_defaults(fn=cmd_rights)

    s = sub.add_parser("forget", help="revoke platform access and delete all stored tokens, queue and settings")
    s.add_argument("--outputs", nargs="*", help="also delete these output folders (clips, reels)")
    s.set_defaults(fn=cmd_forget)

    s = sub.add_parser("trends", help="hashtags trending this week for your topic")
    s.add_argument("--keywords", help='comma-separated topics, e.g. "gta 6,mythpat"')
    s.add_argument("--today", action="store_true", help="only videos uploaded today")
    s.add_argument("--ig-check", type=int, default=0, help="check the top N tags on Instagram (max 30/week)")
    s.add_argument("--save")
    s.set_defaults(fn=cmd_trends)

    def when_opts(s):
        s.add_argument("--tz", default="Asia/Kolkata", help="your audience's time zone")
        s.add_argument("--style", choices=["gaming", "general"], help="audience style (auto from the video)")
        s.add_argument("--start", help="earliest post time, ISO (default: now)")
        s.add_argument("--days", type=int, default=7, help="look this many days ahead")

    s = sub.add_parser("best-times", help="best upcoming times to post")
    s.add_argument("--platforms", default="youtube,instagram")
    s.add_argument("--hot", action="store_true", help="time-sensitive topic: prefer sooner slots")
    s.add_argument("-n", type=int, default=6)
    when_opts(s)
    s.set_defaults(fn=cmd_best_times)

    s = sub.add_parser("plan-posts", help="captions, trending hashtags and best time per reel -> posts.json")
    s.add_argument("--plan", required=True, help="the reel plan.json")
    s.add_argument("--reels", required=True, help="folder with the rendered reels")
    s.add_argument("--url", help="source video (freshness, credit, hashtags)")
    s.add_argument("--moments", help="moments.json from analyze")
    s.add_argument("--keywords", help="topic keywords for trends (default: channel + tags)")
    s.add_argument("--trends", help="saved trends.json to reuse")
    s.add_argument("--platforms", default="youtube,instagram")
    s.add_argument("--gap", type=float, default=20, help="min hours between posts on one platform")
    s.add_argument("--save", default="posts.json")
    when_opts(s)
    s.set_defaults(fn=cmd_plan_posts)

    s = sub.add_parser("publish", help="upload / schedule the posts in posts.json")
    s.add_argument("--posts", required=True)
    s.add_argument("--platforms", default="youtube,instagram")
    s.add_argument("--only", help="post numbers to publish, e.g. 1,3")
    s.add_argument("--now", action="store_true", help="publish immediately instead of at the planned times")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("queue", help="list (or --cancel) scheduled posts")
    s.add_argument("--cancel", help="comma-separated ids")
    s.add_argument("--all", action="store_true", help="include done/failed posts")
    s.set_defaults(fn=cmd_queue)

    sub.add_parser("post-due", help="publish queued posts whose time has come").set_defaults(fn=cmd_post_due)

    s = sub.add_parser("runner", help="keep posting queued reels on time")
    s.add_argument("--install", action="store_true", help="add a Windows scheduled task that runs post-due")
    s.add_argument("--uninstall", action="store_true")
    s.add_argument("--loop", action="store_true", help="run in this window until the queue is empty")
    s.add_argument("--every", type=int, default=10, help="minutes between checks")
    s.set_defaults(fn=cmd_runner)

    a = p.parse_args()
    if hasattr(a, "count"):
        a.count = max(1, min(50, a.count))
        a.length = max(5, min(600, a.length))
    a.fn(a)


if __name__ == "__main__":
    main()
