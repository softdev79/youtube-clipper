"""
Trending hashtags from what is actually being posted *this week*.

For each topic keyword we read YouTube's search results filtered to "uploaded this week" (no API key needed,
via yt-dlp), pull the hashtags out of titles and description snippets, and score each tag by how many
different recent videos/channels use it and how many views those videos got (log-scaled, so one huge video
can't dominate). Tags used by several channels on fresh, well-viewed videos are what's trending now.

Optionally (Instagram connected) the top tags are checked against Instagram's hashtag search for posts in
the last 24 h. Instagram allows only 30 distinct hashtag lookups per 7 days, so that check is opt-in.
"""
import math
import re
import time
import urllib.parse
from collections import defaultdict

HASHTAG = re.compile(r"#([^\s#.,!?;:()\[\]{}\"'|/\\]{2,40})", re.UNICODE)
WEEK = "EgQIAxAB"  # YouTube search filter: upload date = this week, type = video
TODAY = "EgQIAhAB"  # upload date = today

# tags everyone spams: kept only as "broad" reach tags, never counted as topic trends
GENERIC = {"shorts", "short", "youtubeshorts", "ytshorts", "viral", "trending", "reels", "reel", "fyp", "foryou",
           "foryoupage", "explore", "explorepage", "instagram", "instareels", "youtube", "subscribe", "video",
           "viralvideo", "viralshorts", "trendingshorts", "shortsfeed", "shortvideo", "feed", "like", "share",
           "follow", "tiktok", "new", "latest"}


def _search(query, sp=WEEK, n=40):
    import yt_dlp
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query, "sp": sp})
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True,
            "playlistend": n, "noprogress": True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            return (y.extract_info(url, download=False) or {}).get("entries") or []
    except Exception:  # noqa: BLE001
        return []


def _norm(tag):
    return tag.strip().rstrip("…").lower()


def trending_tags(keywords, extra_queries=None, today=False, per_query=40, ig_check=0, log=print):
    """keywords: topic words, e.g. ["gta 6", "mythpat"]. Returns ranked hashtags with evidence."""
    queries = []
    for k in keywords:
        k = k.strip()
        if k:
            queries += [k, f"{k} #shorts"]
    queries += list(extra_queries or [])
    stats = defaultdict(lambda: {"videos": set(), "channels": set(), "score": 0.0, "views": 0, "spelling": {}})
    seen, sample = set(), []
    for q in queries:
        log(f"  trends: searching '{q}'")
        for e in _search(q, TODAY if today else WEEK, per_query):
            vid = e.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            views = int(e.get("view_count") or 0)
            text = f"{e.get('title') or ''} {e.get('description') or ''}"
            tags = {_norm(t): t for t in HASHTAG.findall(text)}
            if views and len(sample) < 12:
                sample.append({"title": e.get("title"), "views": views, "channel": e.get("channel"),
                               "short": (e.get("duration") or 999) <= 180})
            w = 1.0 + math.log10(1 + views)
            for t, raw in tags.items():
                s = stats[t]
                s["videos"].add(vid)
                s["channels"].add(e.get("channel_id") or e.get("channel"))
                s["score"] += w
                s["views"] += views
                s["spelling"][raw] = s["spelling"].get(raw, 0) + 1
        time.sleep(0.5)
    rows = []
    for t, s in stats.items():
        nch = len(s["channels"])
        if nch < 2:  # one channel's own tag isn't a trend
            continue
        spelled = max(s["spelling"], key=s["spelling"].get)
        rows.append({"tag": "#" + spelled, "videos": len(s["videos"]), "channels": nch, "views": s["views"],
                     "score": round(s["score"] * math.sqrt(nch), 1), "generic": t in GENERIC})
    rows.sort(key=lambda r: -r["score"])
    topic = [r for r in rows if not r["generic"]]
    broad = [r for r in rows if r["generic"]]
    sample.sort(key=lambda r: -r["views"])
    out = {"window": "today" if today else "this week", "videos_scanned": len(seen),
           "topic": topic[:25], "broad": broad[:8], "top_recent_videos": sample[:8]}
    if ig_check:
        try:
            import publish
            checks = []
            for r in topic[:ig_check]:
                a = publish.ig_hashtag_activity(r["tag"])
                if a:
                    checks.append(a)
            out["instagram_24h"] = checks
        except Exception as e:  # noqa: BLE001
            out["instagram_24h_error"] = str(e)
    return out


def pick_tags(trend, own=None, platform="instagram", n=None):
    """Final mix: topic trends first, then the creator/video's own tags, then 1-2 broad reach tags.
    Instagram: ~5 focused tags work better than 30. YouTube Shorts: 3 hashtags show above the title."""
    n = n or (5 if platform == "instagram" else 3)
    picked, low = [], set()

    def add(t):
        t = "#" + t.lstrip("#").replace(" ", "")
        if t.lower() not in low and len(picked) < n:
            picked.append(t)
            low.add(t.lower())

    if platform == "youtube":
        add("#Shorts")
    topic = [r["tag"] for r in (trend or {}).get("topic", [])]
    for t in topic[: max(1, n - 2)]:
        add(t)
    for t in own or []:
        add(t)
    for t in topic[max(1, n - 2):]:
        add(t)
    for r in (trend or {}).get("broad", [])[:2]:
        add(r["tag"])
    return picked
