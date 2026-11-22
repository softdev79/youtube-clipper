# YouTube Clipper: notes for Claude

When a user asks you to make clips, highlights or shorts from a YouTube link using this repo, follow the workflow in [skills/clip/SKILL.md](skills/clip/SKILL.md) exactly:
1. Ask how many reels, how long they may be, the output and the platform.
2. Run `cli.py analyze`, then read the transcript (`context`) so every clip keeps its full story, check the layout (`frames`) and render reels (`reel`).
3. Find trending hashtags (`trends`) and plan the best posting times (`plan-posts`).
4. Deliver the ZIP in chat.
5. Publish to YouTube/Instagram (`publish`) only when the user asks and approves the exact posts.

In this repo, `CLI` means `cli.py` at the repository root.

If the user only gave you this repository's GitHub URL and the code isn't on disk yet, clone it first. Then follow the skill:
```
git clone <repo-url> youtube-clipper
python youtube-clipper/cli.py setup
```

Code map:
- `clipper.py`: shared engine (ffmpeg setup, section download with retries, batch + ZIP, hashtag candidates)
- `analyzer.py`: engagement scoring (Most-replayed heatmap, live-chat replay, comment timestamps) and non-overlapping peak picking
- `transcript.py`: captions + context-aware clip edges
- `reel.py`: vertical 9:16 reel renderer
- `dub.py` + `lipsync.py`: translation dubbing (AI voice, Demucs background, optional lip-sync)
- `trends.py`: hashtags trending this week (YouTube search, optional Instagram check)
- `timing.py`: reel priority + best time to post
- `publish.py`: YouTube/Instagram connect, upload, post queue
- `cli.py`: JSON command-line interface used by the skill
- `app.py` + `templates/index.html`: the web app
