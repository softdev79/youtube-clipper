"""
When to post: ranks reels by how likely they are to take off, then gives each one a posting slot.

No tool can guarantee a reel goes viral. What this does is put the odds on your side:
  1. Content check per reel (hook, length, captions, how hot the topic is, how strong the moment was)
     -> a 0-100 "post priority" and whether the topic is time-sensitive.
  2. Audience activity by hour for the platform, in your audience's time zone. It starts from a general
     baseline for short-form entertainment/gaming viewers, then learns from YOUR data when connected:
     Instagram follower-online hours, and how your own past posts performed by posting hour.
  3. The first 1-3 hours decide distribution, so a slot is scored by audience activity over the 3 hours
     after posting (that's why it often lands 30-90 min before the peak).
  4. Hot topics lose value every hour, so time-sensitive reels are pulled earlier (half-life decay).
  5. The best reel gets the best slot; posts on the same platform are spaced out (default 20 h) so they
     don't compete with each other.
"""
import math
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

# Baseline share of the audience that is active, by local hour (0-23). General short-form patterns:
# morning commute, lunch, and a big evening peak; weekends start later and stay busy all afternoon.
_WEEKDAY = [30, 18, 10, 6, 5, 7, 14, 28, 38, 36, 34, 38, 50, 55, 48, 44, 50, 62, 76, 88, 100, 98, 84, 55]
_WEEKEND = [42, 26, 14, 8, 6, 6, 10, 18, 30, 44, 56, 64, 70, 72, 66, 62, 64, 72, 84, 94, 100, 96, 82, 60]
# Gaming / streamer audiences skew later at night; comedy follows the general curve.
_STYLE = {"gaming": [1.15, 1.2, 1.1, 1, 1, 1, 0.9, 0.85, 0.85, 0.9, 0.9, 0.95, 0.95, 0.95, 1, 1, 1, 1, 1, 1, 1.05, 1.1, 1.15, 1.2]}
PLATFORM_SHIFT = {"youtube": 0, "instagram": 0}

DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def tz(name):
    if ZoneInfo is None:
        return timezone(timedelta(hours=5, minutes=30))
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001  (Windows without tzdata)
        return timezone(timedelta(hours=5, minutes=30)) if "Kolkata" in name or "Calcutta" in name else timezone.utc


def _smooth(v, sigma=1.3):
    out = []
    for h in range(24):
        num = den = 0.0
        for d in range(-4, 5):
            w = math.exp(-(d * d) / (2 * sigma * sigma))
            num += w * v[(h + d) % 24]
            den += w
        out.append(num / den)
    return out


class Audience:
    """Hourly activity curve (local time) for one platform, baseline + your own data."""

    def __init__(self, platform, zone, style="general", online_utc=None, history=None):
        self.platform, self.zone = platform, zone
        mult = _STYLE.get(style, [1] * 24)
        self.week = [a * m for a, m in zip(_WEEKDAY, mult)]
        self.wend = [a * m for a, m in zip(_WEEKEND, mult)]
        self.sources = [f"baseline ({style} short-form audience)"]
        if online_utc and sum(online_utc) > 0:
            off = round(datetime.now(zone).utcoffset().total_seconds() / 3600)
            local = [online_utc[(h - off) % 24] for h in range(24)]
            top = max(local)
            local = [100 * x / top for x in local]
            self.week = [0.4 * a + 0.6 * b for a, b in zip(self.week, local)]
            self.wend = [0.4 * a + 0.6 * b for a, b in zip(self.wend, local)]
            self.sources.append("your Instagram followers' online hours")
        self.boost, self.boost_conf = [0.0] * 24, 0.0
        if history:
            self._learn(history)

    def _learn(self, history):
        now = datetime.now(timezone.utc)
        rows = []
        for p in history:
            try:
                t = datetime.fromisoformat(str(p["published"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            age = max(0.5, (now - t).total_seconds() / 86400)
            if age < 2:  # too new to judge
                continue
            v = p.get("views")
            if v is None:
                v = (p.get("likes") or 0) * 20 + (p.get("comments") or 0) * 60
            rows.append((t.astimezone(self.zone).hour, math.log1p(v) - 0.35 * math.log1p(age)))
        if len(rows) < 5:
            return
        mu = sum(r[1] for r in rows) / len(rows)
        sd = (sum((r[1] - mu) ** 2 for r in rows) / len(rows)) ** 0.5 or 1
        acc, wt = [0.0] * 24, [0.0] * 24
        for h0, perf in rows:
            z = (perf - mu) / sd
            for h in range(24):
                d = min(abs(h - h0), 24 - abs(h - h0))
                w = math.exp(-(d * d) / (2 * 1.5 ** 2))
                acc[h] += w * z
                wt[h] += w
        self.boost = [acc[h] / wt[h] if wt[h] > 0.3 else 0.0 for h in range(24)]
        self.boost_conf = len(rows) / (len(rows) + 12)
        self.sources.append(f"how your last {len(rows)} posts performed by posting hour")

    def activity(self, local_dt):
        curve = self.wend if local_dt.weekday() >= 5 else self.week
        h, frac = local_dt.hour, local_dt.minute / 60
        base = curve[h] * (1 - frac) + curve[(h + 1) % 24] * frac
        b = self.boost[h] * (1 - frac) + self.boost[(h + 1) % 24] * frac
        return base * math.exp(0.35 * self.boost_conf * b)

    def window(self, local_dt, hours=3):
        """Average activity over the first `hours` after posting, weighted to the first hour."""
        pts = [(0, 1.0), (0.5, 1.0), (1, 0.8), (1.5, 0.6), (2, 0.5), (2.5, 0.4), (3, 0.3)]
        pts = [(o, w) for o, w in pts if o <= hours]
        return sum(self.activity(local_dt + timedelta(hours=o)) * w for o, w in pts) / sum(w for _, w in pts)

    def peak_hours(self, weekend=False, n=3):
        c = self.wend if weekend else self.week
        return sorted(range(24), key=lambda h: -c[h])[:n]


def analyze_reel(spec, moment_score=None, trend=None, source_age_days=None, keywords=()):
    """Content check for one reel -> priority (0-100), hot/evergreen, reasons."""
    dur = spec.get("seconds") or 0
    pts, why = 50.0, []
    if spec.get("hook"):
        pts += 10
        why.append("cold-open hook grabs the first second")
    if spec.get("captions"):
        pts += 6
        why.append("burned-in captions (most people watch muted)")
    if dur:
        if dur <= 35:
            pts += 10
            why.append(f"{dur:.0f}s: short enough for high completion and rewatches")
        elif dur <= 60:
            pts += 3
            why.append(f"{dur:.0f}s: fine if the story holds")
        else:
            pts -= 6
            why.append(f"{dur:.0f}s: long; completion rate will be lower")
    if moment_score is not None:
        pts += 15 * max(0.0, min(1.0, moment_score))
        if moment_score >= 0.6:
            why.append("one of the most-replayed / most-discussed moments of the stream")
    hot = False
    text = " ".join([spec.get("title", ""), spec.get("subtitle", "")] + list(keywords)).lower()
    hits = [r["tag"] for r in (trend or {}).get("topic", [])[:15]
            if r["tag"].lstrip("#").lower() in text.replace(" ", "")]
    if hits:
        pts += 8
        hot = True
        why.append("topic is trending this week: " + ", ".join(hits[:3]))
    if source_age_days is not None and source_age_days <= 7:
        hot = True
        pts += 6 if source_age_days <= 2 else 3
        why.append(f"source video is {source_age_days:.0f} day(s) old: post while the topic is fresh")
    return {"priority": int(max(0, min(100, round(pts)))), "hot": hot, "reasons": why}


def best_slots(aud, start=None, days=7, step_min=30, hot=False, n=8):
    start = start or datetime.now(timezone.utc) + timedelta(minutes=20)
    t = start.astimezone(aud.zone)
    t = t.replace(minute=(t.minute // step_min) * step_min, second=0, microsecond=0) + timedelta(minutes=step_min)
    out = []
    end = t + timedelta(days=days)
    while t < end:
        hrs = (t - start.astimezone(aud.zone)).total_seconds() / 3600
        decay = 0.5 ** (hrs / 36) if hot else 0.5 ** (hrs / 24 / 14)
        out.append((aud.window(t) * decay, t))
        t += timedelta(minutes=step_min)
    out.sort(key=lambda x: -x[0])
    return out[:n] if n else out


def _fmt(t):
    return f"{DAY[t.weekday()]} {t.strftime('%d %b, %I:%M %p').lstrip('0')}"


def explain(aud, t):
    curve = aud.wend if t.weekday() >= 5 else aud.week
    peak = max(range(24), key=lambda h: curve[h])
    gap = (peak - t.hour) % 24
    if gap == 0:
        lead = "right at the daily peak"
    elif gap <= 3:
        lead = f"{gap} h before the {peak % 12 or 12} {'PM' if peak >= 12 else 'AM'} peak, so it collects its first likes and comments as the audience arrives"
    else:
        lead = "in a strong activity window"
    return lead + (" (weekend)" if t.weekday() >= 5 else "")


def schedule(reels, platforms, zone_name="Asia/Kolkata", start=None, min_gap_h=20, style="general",
             online_utc=None, history=None, days=7):
    """reels: [{name, priority, hot}] (from analyze_reel). Returns per-reel, per-platform slots."""
    zone = tz(zone_name)
    auds = {p: Audience(p, zone, style, online_utc if p == "instagram" else None, (history or {}).get(p))
            for p in platforms}
    order = sorted(range(len(reels)), key=lambda i: -reels[i]["priority"])
    taken = {p: [] for p in platforms}
    plan = [dict(r, slots={}) for r in reels]
    for i in order:
        for p in platforms:
            for score, t in best_slots(auds[p], start, days, hot=reels[i].get("hot"), n=0):
                if all(abs((t - u).total_seconds()) >= min_gap_h * 3600 for u in taken[p]):
                    taken[p].append(t)
                    plan[i]["slots"][p] = {"at": t.isoformat(), "local": _fmt(t), "score": round(score, 1),
                                           "why": explain(auds[p], t)}
                    break
    return {"timezone": zone_name, "based_on": {p: a.sources for p, a in auds.items()},
            "order": [reels[i]["name"] for i in order], "reels": plan}
