# YouTube Clipper

Paste a YouTube video or past live stream. YouTube Clipper finds the moments people **watched and talked about most**, cuts **many clips at once** (MP4 or MP3, never overlapping), bundles them in a ZIP, and **suggests hashtags**.

You can use it two ways, and both produce identical clips because they share the same engine:
- **Through Claude:** paste a link, answer a few questions, and get the clips and hashtags back in chat.
- **As a web app:** run it locally in your browser.

---

## 🤖 Use it from Claude (Claude Code / Claude desktop app → Code)

### Install once
In Claude Code, run:
```
/plugin install youtube-clipper --marketplace softdev79/youtube-clipper
```
On older versions, use two steps instead: `/plugin marketplace add softdev79/youtube-clipper`, then `/plugin install youtube-clipper@youtube-clipper`.

### Then just ask
> make clips from this stream https://www.youtube.com/watch?v=...

Or run the command `/youtube-clipper:clip`. Claude will then:
1. Check the video and which engagement data it has.
2. **Ask you** how many clips you want, how long each one should be, the format (MP4 720p, MP4 1080p or MP3), and where you'll post them.
3. Find the best moments and show them as a table with links and the reason for each pick.
4. Cut all the clips into `./youtube-clips/<video_id>/` and zip them.
5. **Suggest hashtags**: one set for the whole video, plus a title and hashtags for each clip. If web search is available, it adds currently trending tags.
6. Send you the ZIP right in the chat.

On first use, Claude installs the Python dependencies automatically by running `python cli.py setup`.

> Without installing the plugin, you can also give Claude this repo's link. `CLAUDE.md` tells it to clone the repo and follow the same flow.

**Requirements:** Python 3.9+ on the machine where Claude Code runs, with internet access to YouTube. The browser-only claude.ai chat can't download videos, so use Claude Code or the Code tab of the desktop app.

---

## 🌐 Use it as a web app

```powershell
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000, or double-click `run.bat`. Set the `PORT` environment variable to change the port.

1. Paste a link and click **Load video**. Labels under the player show which data the video has.
2. In **🔥 Best moments**, set **how many clips**, the **clip length**, the minimum gap between clips, and optionally **skip intro**. Then click **Find best moments**.
3. Review the moments and suggested hashtags. Preview a moment, edit its times, or untick it.
4. Click **Create N clips**, then **Download all (ZIP)**.

There is also a **Manual clip** section for cutting exact times.

---

## 💻 Command line (what Claude runs)

```powershell
python cli.py setup                                   # install deps + bundled ffmpeg
python cli.py info     URL
python cli.py analyze  URL --count 10 --length 30 --save out/moments.json
python cli.py clip     URL --moments out/moments.json --format mp4 --quality 720 --out out
python cli.py clip     URL --ranges "1:10:03-1:10:23,2:01:24-2:01:44"
python cli.py auto     URL --count 10 --length 30 --out out     # analyze + clip in one go
python cli.py hashtags URL [--moments out/moments.json]
```
Progress goes to stderr, and the result is JSON on stdout.

---

## How the best moments are found

| Signal | Source | Meaning |
|---|---|---|
| 🔁 Most replayed | YouTube's "Most replayed" heatmap | Where watch time and re-watching peak |
| 💬 Live chat | Live-chat replay of past streams (super chats count ×3) | Where chat exploded. Shifted 8 s earlier, because chat reacts late |
| 📝 Comment timestamps | Top ~1000 comments, e.g. "2:31:05 lmao", weighted by likes | Moments viewers point each other to |

Each signal is smoothed, normalised and combined. The top peaks are picked greedily, so clips **never overlap or repeat** and they respect the minimum gap. Each clip starts about 40% of its length before the peak.

**Hashtags** come from the uploader's tags, the description's hashtags, title keywords, and words the audience repeated at the chosen moments. Claude can add live trending tags with web search.

## Notes
- Analysis takes about 1 minute for a 2-hour stream and about 4 minutes for a 5-hour stream. Most of that time is spent downloading the chat replay.
- A stream that is **still live** has no chat replay or heatmap yet. Analyze it after it ends.
- "Most replayed" needs enough views. Chat replay needs a past live stream with replay enabled.
- If YouTube briefly refuses a download (503/403), the clip is retried automatically, up to 4 attempts. If failures persist, run `pip install -U yt-dlp`.
- ffmpeg is bundled through `imageio-ffmpeg`, so there's nothing extra to install.
- Only clip content you have the right to use, such as your own videos, Creative Commons, or fair use.

## Files
- `clipper.py`: shared engine (ffmpeg, section download and retries, batch and ZIP, hashtags)
- `analyzer.py`: engagement scoring and non-overlapping moment picking
- `cli.py`: JSON command line used by Claude
- `app.py`, `templates/index.html`: web app
- `.claude-plugin/`, `skills/clip/SKILL.md`: Claude Code plugin and the guided clipping skill
- `CLAUDE.md`: instructions for Claude when the repo is cloned directly

MIT License.
