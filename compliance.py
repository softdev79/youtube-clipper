"""
Rights confirmation and AI-disclosure helpers shared by the CLI, the web app and the publisher.

Before the tool downloads any part of a video, the person using it confirms once that they own the
video or have the creator's permission (see TERMS.md). The confirmation is stored locally in
~/.youtube-clipper/rights.json with the terms version and the time it was given; nothing is sent anywhere.

Reels with an AI voice (dubbing) or AI lip-sync are "altered or synthetic" content. They get a visible
on-video label, a line in the post text and YouTube's containsSyntheticMedia flag.
"""
import json
import os
from datetime import datetime, timezone

HOME = os.environ.get("YTCLIPPER_HOME") or os.path.join(os.path.expanduser("~"), ".youtube-clipper")
RIGHTS = os.path.join(HOME, "rights.json")
TERMS_VERSION = "2026-11-24"

NOTICE = (
    "Before clipping, confirm that you own this video or have the creator's permission to clip and "
    "repost it, and that you'll follow YouTube's Terms of Service (https://www.youtube.com/t/terms), "
    "the Instagram Terms of Use and copyright law where you live. Reels with an AI voice or lip-sync "
    "are labelled as AI-altered. Full terms: TERMS.md; privacy: PRIVACY.md."
)

AI_LABEL_DUB = "AI-dubbed voice"
AI_LABEL_LIPS = "AI-dubbed voice & lip-sync"
AI_POST_LINE = "🤖 Altered with AI: the voice{lips} in this clip is AI-generated from a translation of the original."


def status():
    try:
        with open(RIGHTS, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    ok = d.get("version") == TERMS_VERSION and d.get("accepted") is True
    return {"accepted": ok, "version": TERMS_VERSION, "accepted_at": d.get("at") if ok else None,
            "notice": NOTICE}


def accepted():
    return status()["accepted"]


def accept():
    os.makedirs(HOME, exist_ok=True)
    with open(RIGHTS, "w", encoding="utf-8") as fh:
        json.dump({"accepted": True, "version": TERMS_VERSION,
                   "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, fh, indent=2)
    return status()


def revoke():
    if os.path.exists(RIGHTS):
        os.remove(RIGHTS)
    return status()


def ai_label(spec):
    """Visible label for a reel spec, or "" when the reel has no synthetic audio/video."""
    d = spec.get("dub") or {}
    if not d:
        return ""
    return AI_LABEL_LIPS if d.get("lipsync") not in (None, "", "none") else AI_LABEL_DUB


def ai_post_line(spec):
    d = spec.get("dub") or {}
    if not d:
        return ""
    return AI_POST_LINE.format(lips=" and lip movement" if d.get("lipsync") not in (None, "", "none") else "")
