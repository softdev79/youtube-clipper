"""
YouTube Clipper web app - paste a YouTube link, find the most engaging moments
(most-replayed, live-chat spikes, comment timestamps) and cut many clips at once.

Run:  python app.py   then open http://127.0.0.1:5000
The same engine is available to Claude / the terminal via cli.py.
"""
import os
import threading
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory

import analyzer
import clipper
from clipper import MAX_BATCH, MAX_CLIP_SECONDS, clean_err, parse_time, valid_url

CLIPS_DIR = os.path.join(clipper.BASE_DIR, "clips")
os.makedirs(CLIPS_DIR, exist_ok=True)

app = Flask(__name__)
jobs = {}


def new_job(**fields):
    job_id = uuid.uuid4().hex
    jobs[job_id] = dict(status="queued", progress=0, error=None, **fields)
    return job_id


# ---------------------------------------------------------------- workers
def run_single(job_id, url, start, end, mode, height):
    job = jobs[job_id]

    def prog(status, pct):
        job["status"] = status
        if pct is not None:
            job["progress"] = pct

    try:
        job["status"] = "starting"
        job["file"] = clipper.make_clip(url, start, end, mode, height, job_id[:8], CLIPS_DIR, prog)
        job.update(status="done", progress=100)
    except Exception as e:  # noqa: BLE001
        job.update(status="error", error=clean_err(e))


def run_analyze(job_id, url, n, clip_len, gap, sources, skip_start, smart=True):
    job = jobs[job_id]

    def prog(msg):
        job["message"] = msg

    try:
        job["status"] = "running"
        if smart:   # clip_len = longest allowed clip; edges follow the conversation
            job["result"] = analyzer.analyze(url, n, min(30, clip_len), gap, sources, skip_start, prog,
                                             smart=True, min_len=min(20, clip_len), max_len=clip_len)
        else:
            job["result"] = analyzer.analyze(url, n, clip_len, gap, sources, skip_start, prog, smart=False)
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        job.update(status="error", error=clean_err(e))


def run_batch(job_id, url, mode, height):
    job = jobs[job_id]
    job["status"] = "running"
    res = clipper.make_batch(url, None, mode, height, CLIPS_DIR, job_id[:6], items=job["clips"])
    job["zip"] = res["zip"]
    job["status"] = "done" if res["zip"] else "error"
    if not res["zip"]:
        job["error"] = "All clips failed."


# ---------------------------------------------------------------- routes
@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/info")
def info():
    url = (request.json or {}).get("url", "").strip()
    if not valid_url(url):
        return jsonify(error="That doesn't look like a YouTube video link."), 400
    try:
        data = clipper.video_info(url)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Could not read video: {clean_err(e)}"), 400
    data.pop("description", None)
    return jsonify(data)


@app.post("/api/analyze")
def analyze_route():
    b = request.json or {}
    url = b.get("url", "").strip()
    if not valid_url(url):
        return jsonify(error="Invalid YouTube link."), 400
    try:
        n = max(1, min(MAX_BATCH, int(b.get("count", 5))))
        clip_len = max(5, min(600, int(b.get("clip_len", 30))))
        gap = max(0, min(3600, int(b.get("gap", 10))))
        skip_start = max(0, int(float(b.get("skip_start_min", 0)) * 60))
    except (TypeError, ValueError):
        return jsonify(error="Clip count, length, gap and skip must be numbers."), 400
    sources = [s for s in b.get("sources", ["heatmap", "chat", "comments"])
               if s in ("heatmap", "chat", "comments")]
    if not sources:
        return jsonify(error="Pick at least one signal."), 400
    job_id = new_job(message="Queued…", result=None)
    threading.Thread(target=run_analyze, daemon=True,
                     args=(job_id, url, n, clip_len, gap, sources, skip_start,
                           bool(b.get("smart", True)))).start()
    return jsonify(job_id=job_id)


@app.post("/api/clip")
def clip():
    body = request.json or {}
    url = body.get("url", "").strip()
    if not valid_url(url):
        return jsonify(error="Invalid YouTube link."), 400
    try:
        start, end = parse_time(body.get("start", "")), parse_time(body.get("end", ""))
    except ValueError as e:
        return jsonify(error=f"Bad time format ({e}). Use 90, 1:30 or 1:01:30."), 400
    duration = float(body.get("duration") or 0)
    if duration and end > duration:
        end = duration
    if end <= start:
        return jsonify(error="End time must be after start time."), 400
    if end - start > MAX_CLIP_SECONDS:
        return jsonify(error="Clips are limited to 1 hour."), 400
    mode = "mp3" if body.get("mode") == "mp3" else "mp4"
    job_id = new_job(file=None)
    threading.Thread(target=run_single, args=(job_id, url, start, end, mode, str(body.get("height", "720"))),
                     daemon=True).start()
    return jsonify(job_id=job_id)


@app.post("/api/batch")
def batch():
    b = request.json or {}
    url = b.get("url", "").strip()
    if not valid_url(url):
        return jsonify(error="Invalid YouTube link."), 400
    try:
        clips = clipper.validate_ranges([(c["start"], c["end"]) for c in (b.get("clips") or [])])
    except (KeyError, TypeError, ValueError) as e:
        return jsonify(error=str(e)), 400
    mode = "mp3" if b.get("mode") == "mp3" else "mp4"
    job_id = new_job(zip=None, clips=[{"start": s, "end": e, "status": "queued", "progress": 0,
                                       "file": None, "error": None} for s, e in clips])
    threading.Thread(target=run_batch, args=(job_id, url, mode, str(b.get("height", "720"))),
                     daemon=True).start()
    return jsonify(job_id=job_id)


@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error="Unknown job"), 404
    return jsonify(job)


@app.get("/clips/<path:name>")
def download(name):
    return send_from_directory(CLIPS_DIR, name, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"YouTube Clipper running at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
