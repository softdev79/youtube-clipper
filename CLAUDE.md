# YouTube Clipper: notes for Claude

When a user asks you to make clips, highlights or shorts from a YouTube link using this repo, follow the workflow in [skills/clip/SKILL.md](skills/clip/SKILL.md) exactly:
1. Ask how many clips, how long each clip should be, the format and the platform.
2. Run `cli.py` to analyze and cut the clips.
3. Suggest hashtags.
4. Deliver the ZIP in chat.

In this repo, `CLI` means `cli.py` at the repository root.

If the user only gave you this repository's GitHub URL and the code isn't on disk yet, clone it first. Then follow the skill:
```
git clone <repo-url> youtube-clipper
python youtube-clipper/cli.py setup
```

Code map:
- `clipper.py`: shared engine (ffmpeg setup, section download with retries, batch + ZIP, hashtag candidates)
- `analyzer.py`: engagement scoring (Most-replayed heatmap, live-chat replay, comment timestamps) and non-overlapping peak picking
- `cli.py`: JSON command-line interface used by the skill
- `app.py` + `templates/index.html`: the web app
