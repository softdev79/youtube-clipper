"""
Lip-sync: make the speaker's mouth match the dubbed voice.

Backends:
  none   keep the original video (the dub is timed to the speech, the mouth isn't changed)
  sync   sync.so cloud API (lipsync-2). Set SYNC_API_KEY or put {"sync_api_key": "..."} in
         ~/.youtube-clipper/keys.json. Paid per second of video. Status: implemented, not yet tested against a
         live key.

Run on the dubbed source clip *before* the 9:16 layout, so the model sees the full-size face.
"""
import json
import os
import time

import requests

KEYS = os.path.join(os.environ.get("YTCLIPPER_HOME") or os.path.join(os.path.expanduser("~"), ".youtube-clipper"),
                    "keys.json")
SYNC_API = "https://api.sync.so/v2"


def _key(name, env):
    if os.environ.get(env):
        return os.environ[env]
    try:
        with open(KEYS, encoding="utf-8") as fh:
            return json.load(fh).get(name)
    except (OSError, ValueError):
        return None


def available():
    return {"none": True, "sync": bool(_key("sync_api_key", "SYNC_API_KEY"))}


def sync_so(video, voice_audio, out, model="lipsync-2", log=print, timeout_min=30):
    key = _key("sync_api_key", "SYNC_API_KEY")
    if not key:
        raise RuntimeError("Lip-sync needs a sync.so API key: set SYNC_API_KEY or add sync_api_key to " + KEYS)
    h = {"x-api-key": key}
    log("    lip-sync: uploading to sync.so…")
    with open(video, "rb") as v, open(voice_audio, "rb") as a:
        r = requests.post(f"{SYNC_API}/generate", headers=h, timeout=600,
                          files={"video": (os.path.basename(video), v, "video/mp4"),
                                 "audio": (os.path.basename(voice_audio), a, "audio/wav")},
                          data={"model": model, "options": json.dumps({"sync_mode": "cut_off"})})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"sync.so {r.status_code}: {r.text[:300]}")
    job = r.json()["id"]
    for _ in range(timeout_min * 6):
        time.sleep(10)
        st = requests.get(f"{SYNC_API}/generate/{job}", headers=h, timeout=60).json()
        s = st.get("status")
        if s == "COMPLETED":
            url = st.get("outputUrl")
            with requests.get(url, stream=True, timeout=600) as d, open(out, "wb") as fh:
                for chunk in d.iter_content(1 << 20):
                    fh.write(chunk)
            return out
        if s in ("FAILED", "REJECTED", "CANCELED"):
            raise RuntimeError(f"sync.so job {s}: {st.get('error')}")
        log(f"    lip-sync: {s}…")
    raise RuntimeError("sync.so took too long")


def apply(backend, video, voice_audio, mixed_audio, out, ffmpeg, log=print):
    """Lip-sync `video` to `voice_audio`, then put `mixed_audio` (voice + background) back on it."""
    if backend in (None, "", "none"):
        return video
    if backend != "sync":
        raise ValueError(f"Unknown lip-sync backend {backend}")
    synced = out + ".lips.mp4"
    sync_so(video, voice_audio, synced, log=log)
    import subprocess
    r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", synced, "-i", mixed_audio,
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", out],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-400:])
    return out
