"""
Publishing to YouTube (Shorts) and Instagram (Reels), plus a post queue for scheduled posting.

Credentials live in ~/.youtube-clipper/ (never inside the repo):
  youtube_client.json   OAuth "Desktop app" client from your own Google Cloud project
  youtube_token.json    refresh/access token written by `cli.py connect youtube`
  instagram.json        {"access_token", "ig_user_id", "username", "host", "version"}
  queue.json            scheduled posts waiting for `cli.py post-due`

YouTube: OAuth (loopback + PKCE) and resumable upload, using `requests` only. A scheduled YouTube post
is uploaded right away as private with status.publishAt, so YouTube itself publishes it on time.
Note: Google keeps uploads from API projects that haven't passed the YouTube API audit private.

Instagram: Graph API content publishing (Business or Creator account). The reel goes up as a resumable
upload to rupload.facebook.com, waits for processing, then media_publish. The Instagram API has no
scheduling, so queued Instagram posts are sent by `cli.py post-due`, run on a timer (`cli.py runner`).
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import threading
import time
import urllib.parse
import uuid
import webbrowser
from datetime import datetime, timezone

import requests

HOME = os.environ.get("YTCLIPPER_HOME") or os.path.join(os.path.expanduser("~"), ".youtube-clipper")
YT_CLIENT = os.path.join(HOME, "youtube_client.json")
YT_TOKEN = os.path.join(HOME, "youtube_token.json")
IG_CONF = os.path.join(HOME, "instagram.json")
QUEUE = os.path.join(HOME, "queue.json")

YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
             "https://www.googleapis.com/auth/youtube.readonly"]
YT_API = "https://www.googleapis.com/youtube/v3"
IG_VERSION = "v25.0"
TIMEOUT = 60
POLICY_NOTICE = ("This tool uses YouTube API Services. By connecting, you agree to the YouTube Terms of Service "
                 "(https://www.youtube.com/t/terms); Google's Privacy Policy (https://policies.google.com/privacy) "
                 "applies. Tokens stay on this computer only. Revoke access any time with "
                 "`python cli.py accounts --disconnect youtube` or at https://myaccount.google.com/permissions.")


class PublishError(Exception):
    pass


def _load(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(HOME, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_when(s):
    """ISO time (with offset, or 'Z') -> aware datetime. Naive times are treated as local time."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.astimezone()
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.astimezone()


def _err(r):
    try:
        j = r.json()
        e = j.get("error", j)
        if isinstance(e, dict):
            return f"{r.status_code}: {e.get('message') or e.get('error_description') or e}"
        return f"{r.status_code}: {j.get('error_description') or e}"
    except ValueError:
        return f"{r.status_code}: {r.text[:300]}"


# ================================================================ YouTube
def _client():
    c = _load(YT_CLIENT)
    if not c:
        raise PublishError("YouTube isn't connected. Run: python cli.py connect youtube --client-secret client_secret.json")
    c = c.get("installed") or c.get("web") or c
    if not c.get("client_id"):
        raise PublishError("youtube_client.json has no client_id. Download the OAuth client JSON "
                           "(type: Desktop app) from Google Cloud Console.")
    return c


def yt_connect(client_secret_path=None, open_browser=True, log=print):
    if client_secret_path:
        if not os.path.isfile(client_secret_path):
            raise PublishError(f"File not found: {client_secret_path}")
        os.makedirs(HOME, exist_ok=True)
        shutil.copyfile(client_secret_path, YT_CLIENT)
    c = _client()

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "YouTube connected. You can close this tab." if "code" in q else "Sign-in was cancelled."
            self.wfile.write(f"<h2 style='font-family:sans-serif'>{msg}</h2>".encode())

        def log_message(self, *_):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(YT_SCOPES), "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state})
    log(POLICY_NOTICE)
    log("Opening Google sign-in in your browser. If it doesn't open, visit:\n" + url)
    if open_browser:
        webbrowser.open(url)
    t = threading.Thread(target=lambda: [srv.handle_request() for _ in range(5) if not got], daemon=True)
    t.start()
    t.join(300)
    srv.server_close()
    if not got:
        raise PublishError("No answer from Google sign-in within 5 minutes.")
    if got.get("error"):
        raise PublishError(f"Google sign-in failed: {got['error']}")
    if got.get("state") != state:
        raise PublishError("Sign-in state mismatch; try again.")

    r = requests.post("https://oauth2.googleapis.com/token", timeout=TIMEOUT, data={
        "code": got["code"], "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
    if r.status_code != 200:
        raise PublishError("Token exchange failed: " + _err(r))
    tok = r.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    _save(YT_TOKEN, tok)
    ch = yt_channel()
    tok["channel"] = ch
    _save(YT_TOKEN, tok)
    return ch


def _yt_token():
    tok = _load(YT_TOKEN)
    if not tok:
        raise PublishError("YouTube isn't connected. Run: python cli.py connect youtube --client-secret client_secret.json")
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise PublishError("YouTube sign-in expired. Run: python cli.py connect youtube")
    c = _client()
    r = requests.post("https://oauth2.googleapis.com/token", timeout=TIMEOUT, data={
        "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise PublishError("YouTube sign-in expired (" + _err(r) + "). Run: python cli.py connect youtube")
    j = r.json()
    tok["access_token"] = j["access_token"]
    tok["expires_at"] = time.time() + j.get("expires_in", 3600) - 60
    _save(YT_TOKEN, tok)
    return tok["access_token"]


def _yt_get(path, **params):
    r = requests.get(f"{YT_API}/{path}", params=params, timeout=TIMEOUT,
                     headers={"Authorization": "Bearer " + _yt_token()})
    if r.status_code != 200:
        raise PublishError("YouTube API " + _err(r))
    return r.json()


def yt_channel():
    items = _yt_get("channels", part="snippet,statistics,contentDetails", mine="true").get("items") or []
    if not items:
        raise PublishError("This Google account has no YouTube channel.")
    c = items[0]
    return {"id": c["id"], "title": c["snippet"]["title"],
            "subscribers": int(c["statistics"].get("subscriberCount", 0) or 0),
            "videos": int(c["statistics"].get("videoCount", 0) or 0),
            "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"]}


def _yt_text(s, n):
    s = (s or "").replace("<", "").replace(">", "")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def yt_upload(path, title, description="", tags=None, publish_at=None, privacy="public",
              category="20", made_for_kids=False, log=print, synthetic=False):
    """Upload a Short. publish_at (datetime/ISO) -> uploaded private now, YouTube publishes it then.
    synthetic=True sets YouTube's altered/synthetic content disclosure (AI voice or lip-sync)."""
    if not os.path.isfile(path):
        raise PublishError(f"File not found: {path}")
    title = _yt_text(title, 100)
    if "#shorts" not in (title + " " + description).lower():
        description = (description.rstrip() + "\n\n#Shorts").strip()
    tags, used = [t.lstrip("#") for t in (tags or [])], 0
    keep = []
    for t in tags:
        if used + len(t) + 3 > 480:
            break
        keep.append(t)
        used += len(t) + 3
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids),
              "containsSyntheticMedia": bool(synthetic)}
    if publish_at:
        when = parse_when(publish_at)
        if when > datetime.now(timezone.utc):
            status = {**status, "privacyStatus": "private", "publishAt": iso_utc(when)}
    body = {"snippet": {"title": title, "description": _yt_text(description, 5000), "tags": keep,
                        "categoryId": str(category)},
            "status": status}
    size = os.path.getsize(path)
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos",
                      params={"uploadType": "resumable", "part": "snippet,status"}, json=body, timeout=TIMEOUT,
                      headers={"Authorization": "Bearer " + _yt_token(),
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    if r.status_code != 200:
        raise PublishError("YouTube upload start failed: " + _err(r))
    loc, chunk, sent, res = r.headers["Location"], 8 * 1024 * 1024, 0, None
    with open(path, "rb") as fh:
        while sent < size:
            fh.seek(sent)
            data = fh.read(chunk)
            for attempt in range(5):
                try:
                    rr = requests.put(loc, data=data, timeout=300, headers={
                        "Authorization": "Bearer " + _yt_token(),
                        "Content-Range": f"bytes {sent}-{sent + len(data) - 1}/{size}"})
                except requests.RequestException as e:
                    rr = e
                if not isinstance(rr, Exception) and rr.status_code in (200, 201, 308):
                    break
                time.sleep(2 ** attempt)
            else:
                raise PublishError("YouTube upload failed: " + (_err(rr) if not isinstance(rr, Exception) else str(rr)))
            if rr.status_code in (200, 201):
                res, sent = rr.json(), size
            else:
                rng = rr.headers.get("Range")
                sent = int(rng.split("-")[1]) + 1 if rng else sent + len(data)
                log(f"  YouTube upload {100 * sent // size}%")
    vid = res["id"]
    st = res.get("status", {})
    out = {"platform": "youtube", "id": vid, "url": f"https://youtube.com/shorts/{vid}",
           "privacy": st.get("privacyStatus"), "publish_at": st.get("publishAt")}
    if st.get("privacyStatus") == "private" and not publish_at and privacy != "private":
        out["warning"] = ("YouTube set this upload to private. Your Google Cloud project probably hasn't passed "
                          "the YouTube API audit yet: make it public in YouTube Studio, or apply for the audit.")
    return out


def yt_history(limit=50):
    """Your recent uploads with publish time and stats (for best-time learning)."""
    ch = yt_channel()
    ids, page = [], None
    while len(ids) < limit:
        j = _yt_get("playlistItems", part="contentDetails", playlistId=ch["uploads"], maxResults=50,
                    **({"pageToken": page} if page else {}))
        ids += [i["contentDetails"]["videoId"] for i in j.get("items", [])]
        page = j.get("nextPageToken")
        if not page:
            break
    out = []
    for k in range(0, min(len(ids), limit), 50):
        j = _yt_get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[k:k + 50]))
        for v in j.get("items", []):
            s = v.get("statistics", {})
            out.append({"id": v["id"], "published": v["snippet"]["publishedAt"], "title": v["snippet"]["title"],
                        "duration": v["contentDetails"].get("duration"),
                        "views": int(s.get("viewCount", 0) or 0), "likes": int(s.get("likeCount", 0) or 0),
                        "comments": int(s.get("commentCount", 0) or 0)})
    return out


# ================================================================ Instagram
def _ig():
    c = _load(IG_CONF)
    if not c or not c.get("access_token"):
        raise PublishError("Instagram isn't connected. Run: python cli.py connect instagram --token <ACCESS_TOKEN>")
    c.setdefault("host", "graph.facebook.com")
    c.setdefault("version", IG_VERSION)
    return c


def _ig_call(method, path, conf=None, **params):
    c = conf or _ig()
    params["access_token"] = c["access_token"]
    url = f"https://{c['host']}/{c['version']}/{path}"
    r = requests.request(method, url, params=params if method == "GET" else None,
                         data=params if method != "GET" else None, timeout=TIMEOUT)
    if r.status_code != 200:
        raise PublishError("Instagram API " + _err(r))
    return r.json()


def ig_connect(token, ig_user_id=None, host=None, version=None):
    host = host or ("graph.instagram.com" if token.startswith("IG") else "graph.facebook.com")
    conf = {"access_token": token.strip(), "host": host, "version": version or IG_VERSION}
    if not ig_user_id:
        if host == "graph.instagram.com":
            me = _ig_call("GET", "me", conf, fields="user_id,username")
            ig_user_id = me.get("user_id") or me.get("id")
        else:
            accts = []
            try:  # classic Facebook-login tokens: Instagram account linked to a Page
                pages = _ig_call("GET", "me/accounts", conf, fields="name,instagram_business_account{id,username}")
                accts = [p["instagram_business_account"]["id"] for p in pages.get("data", [])
                         if p.get("instagram_business_account")]
            except PublishError:
                pass
            if not accts:  # Unified login / business-asset tokens: the account is granted to the token directly
                try:
                    dbg = _ig_call("GET", "debug_token", conf, input_token=conf["access_token"]).get("data", {})
                    for g in dbg.get("granular_scopes", []):
                        if g.get("scope", "").startswith("instagram") and g.get("target_ids"):
                            accts += [t for t in g["target_ids"] if t not in accts]
                except PublishError:  # needs an app-owner token; business/system-user tokens can't call it
                    pass
            if not accts:  # Instagram accounts owned by the token's business portfolio(s)
                try:
                    for b in _ig_call("GET", "me/businesses", conf, fields="id").get("data", []):
                        for edge in ("owned_instagram_accounts", "instagram_business_accounts", "instagram_accounts"):
                            try:
                                rows = _ig_call("GET", f"{b['id']}/{edge}", conf, fields="id,username").get("data", [])
                            except PublishError:
                                continue
                            accts += [r["id"] for r in rows if r.get("id") and r["id"] not in accts]
                            if accts:
                                break
                except PublishError:
                    pass
            if not accts:
                raise PublishError("This token can't see any Instagram Professional account. Generate the token again "
                                   "and pick your Instagram account in the 'business assets' step, or pass "
                                   "--ig-user-id (Business settings > Accounts > Instagram accounts > ID).")
            ig_user_id = accts[0]
    me = _ig_call("GET", str(ig_user_id), conf, fields="username,followers_count,media_count")
    conf.update({"ig_user_id": str(ig_user_id), "username": me.get("username"),
                 "followers": me.get("followers_count"), "connected": iso_utc(datetime.now(timezone.utc))})
    _save(IG_CONF, conf)
    return {k: conf[k] for k in ("ig_user_id", "username", "followers", "host")}


def ig_caption(caption, hashtags=None):
    tags = []
    for h in hashtags or []:
        h = "#" + h.lstrip("#")
        if h.lower() not in caption.lower() and h not in tags:
            tags.append(h)
    total = caption.count("#")
    text = caption.rstrip() + ("\n\n" + " ".join(tags[: max(0, 30 - total)]) if tags else "")
    return text[:2200]


def ig_upload(path, caption, share_to_feed=True, cover_ms=None, log=print):
    if not os.path.isfile(path):
        raise PublishError(f"File not found: {path}")
    c = _ig()
    uid = c["ig_user_id"]
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
              "share_to_feed": "true" if share_to_feed else "false"}
    if cover_ms is not None:
        params["thumb_offset"] = int(cover_ms)
    cont = _ig_call("POST", f"{uid}/media", c, **params)
    cid = cont["id"]
    up = cont.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{c['version']}/{cid}"
    size = os.path.getsize(path)
    log(f"  Instagram: uploading {size / 1e6:.1f} MB")
    with open(path, "rb") as fh:
        r = requests.post(up, data=fh, timeout=600, headers={
            "Authorization": f"OAuth {c['access_token']}", "offset": "0", "file_size": str(size)})
    if r.status_code != 200:
        raise PublishError("Instagram video upload failed: " + _err(r))
    for _ in range(120):  # up to ~10 min of processing
        st = _ig_call("GET", cid, c, fields="status_code,status")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise PublishError(f"Instagram couldn't process the video: {st.get('status') or code}")
        time.sleep(5)
    else:
        raise PublishError("Instagram is still processing the video after 10 minutes; try `post-due` again later.")
    pub = _ig_call("POST", f"{uid}/media_publish", c, creation_id=cid)
    mid = pub["id"]
    try:
        link = _ig_call("GET", mid, c, fields="permalink").get("permalink")
    except PublishError:
        link = None
    return {"platform": "instagram", "id": mid, "url": link}


def ig_history(limit=50):
    c = _ig()
    j = _ig_call("GET", f"{c['ig_user_id']}/media", c, limit=min(limit, 100),
                 fields="id,timestamp,media_type,media_product_type,like_count,comments_count,permalink")
    out = []
    for m in j.get("data", []):
        row = {"id": m["id"], "published": m["timestamp"], "type": m.get("media_product_type") or m.get("media_type"),
               "likes": m.get("like_count", 0), "comments": m.get("comments_count", 0), "views": None}
        try:
            ins = _ig_call("GET", f"{m['id']}/insights", c, metric="views,reach")
            for d in ins.get("data", []):
                v = (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value"))
                row[d["name"]] = v
        except PublishError:
            pass
        out.append(row)
    return out


def ig_online_followers():
    """Hour-of-day follower activity (UTC hours) if Instagram still provides it, else None."""
    c = _ig()
    try:
        j = _ig_call("GET", f"{c['ig_user_id']}/insights", c, metric="online_followers", period="lifetime")
    except PublishError:
        return None
    acc = [0.0] * 24
    for d in j.get("data", []):
        for v in d.get("values", []):
            for h, n in (v.get("value") or {}).items():
                acc[int(h) % 24] += float(n or 0)
    return acc if any(acc) else None


def ig_hashtag_activity(tag):
    """Recent posts + engagement for a hashtag (Instagram allows only 30 distinct lookups per 7 days)."""
    c = _ig()
    found = _ig_call("GET", "ig_hashtag_search", c, user_id=c["ig_user_id"], q=tag.lstrip("#"))
    if not found.get("data"):
        return None
    hid = found["data"][0]["id"]
    j = _ig_call("GET", f"{hid}/recent_media", c, user_id=c["ig_user_id"], limit=50,
                 fields="timestamp,like_count,comments_count")
    now, n24, eng = datetime.now(timezone.utc), 0, 0
    for m in j.get("data", []):
        if (now - parse_when(m["timestamp"])).total_seconds() < 86400:
            n24 += 1
            eng += (m.get("like_count") or 0) + (m.get("comments_count") or 0)
    return {"tag": "#" + tag.lstrip("#"), "posts_24h_sample": n24, "engagement_24h_sample": eng}


# ================================================================ accounts
def accounts():
    out = {"config_dir": HOME}
    tok = _load(YT_TOKEN)
    out["youtube"] = {"connected": bool(tok), **({"channel": tok.get("channel")} if tok else {})}
    ig = _load(IG_CONF)
    out["instagram"] = ({"connected": True, "username": ig.get("username"), "ig_user_id": ig.get("ig_user_id"),
                         "host": ig.get("host")} if ig else {"connected": False})
    return out


def disconnect(platform):
    """Revoke the grant with the platform (best effort), then delete the stored token.
    Returns True when the platform confirmed the revoke, False when it didn't, None when nothing was stored."""
    revoked = None
    if platform == "youtube":
        tok = _load(YT_TOKEN)
        if tok:
            t = tok.get("refresh_token") or tok.get("access_token")
            try:
                r = requests.post("https://oauth2.googleapis.com/revoke", data={"token": t}, timeout=TIMEOUT)
                revoked = r.status_code == 200
            except requests.RequestException:
                revoked = False
        files = [YT_TOKEN]
    else:
        c = _load(IG_CONF)
        if c and c.get("host") == "graph.facebook.com":   # Facebook-login tokens can drop their own grant
            try:
                r = requests.delete(f"https://graph.facebook.com/{c.get('version') or IG_VERSION}/me/permissions",
                                    params={"access_token": c["access_token"]}, timeout=TIMEOUT)
                revoked = r.status_code == 200
            except requests.RequestException:
                revoked = False
        elif c:
            revoked = False   # Instagram-login tokens: remove the app in Instagram > Settings > Apps and websites
        files = [IG_CONF]
    for f in files:
        if os.path.exists(f):
            os.remove(f)
    return revoked


# ================================================================ queue
def publish_one(job, log=print):
    if job["platform"] == "youtube":
        return yt_upload(job["file"], job["title"], job.get("description", ""), job.get("tags"),
                         publish_at=job.get("at"), log=log, synthetic=bool(job.get("synthetic")))
    if job["platform"] == "instagram":
        return ig_upload(job["file"], job["caption"], log=log, cover_ms=job.get("cover_ms"))
    raise PublishError(f"Unknown platform {job['platform']}")


def queue_load():
    return _load(QUEUE, [])


def queue_add(jobs):
    q = queue_load()
    for j in jobs:
        j.setdefault("id", uuid.uuid4().hex[:8])
        j.setdefault("status", "pending")
        j.setdefault("attempts", 0)
        j["file"] = os.path.abspath(j["file"])
        q.append(j)
    _save(QUEUE, q)
    return q


def queue_cancel(ids):
    q = queue_load()
    for j in q:
        if j["id"] in ids and j["status"] == "pending":
            j["status"] = "cancelled"
    _save(QUEUE, q)
    return q


def post_due(now=None, log=print, max_attempts=3):
    """Publish every pending queued post whose time has come."""
    now = now or datetime.now(timezone.utc)
    q, done = queue_load(), []
    for j in q:
        if j["status"] != "pending" or parse_when(j["at"]) > now:
            continue
        log(f"Posting {os.path.basename(j['file'])} to {j['platform']}…")
        j["attempts"] += 1
        try:
            j["result"] = publish_one(j, log=log)
            j["status"] = "done"
            j["posted"] = iso_utc(datetime.now(timezone.utc))
        except Exception as e:  # noqa: BLE001
            j["error"] = str(e)
            if j["attempts"] >= max_attempts:
                j["status"] = "failed"
        _save(QUEUE, q)
        done.append(j)
    return done
