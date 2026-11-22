# YouTube Clipper

Paste a YouTube video or past live stream. YouTube Clipper finds the moments people **watched and talked about most**, **reads what is being said so every clip keeps its full context** (setup → payoff, 20–90 s instead of a blind fixed length), and turns them into **viral-ready vertical reels**: 9:16, hook title card, burned-in captions, jump cuts, optional cold open, sharpened 1440p source, loudness-normalised audio. It also cuts plain MP4/MP3 clips (never overlapping), bundles everything in a ZIP, can **dub reels into another language**, finds **hashtags trending this week**, predicts the **best time to post** each reel, and can **upload and schedule** them to your YouTube channel (Shorts) and Instagram (Reels).

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

Or run the command `/youtube-clipper:clip`. Claude then works as your short-form editor:
1. Checks the video and which engagement data it has.
2. **Asks you** how many reels, how long they may be (auto 20–60 s, up to 90 s, or exact), the output (vertical reels, plain MP4 or MP3), and the platform.
3. Finds candidate moments (Most-replayed, chat spikes, comment timestamps), then **reads the transcript around each one**. It keeps only stories that make sense to a stranger, sets the edges from setup to payoff, merges halves of the same story, drops strike-risk content and removes dead air with jump cuts.
4. Looks at the frames to choose the layout per segment: full shot, camera over gameplay, enlarged facecam, or whole frame.
5. Writes a hook title, Roman-script captions (e.g. Hinglish for Hindi creators) and an optional cold open, then renders 1080×1920 reels into `./youtube-clips/<video_id>/reels/` with a ZIP.
6. Checks frames of every reel, then **suggests a caption and hashtags per reel** plus a set for the whole video (with live trends if web search is available).
7. Sends you the reels right in the chat.

On first use, Claude installs the Python dependencies automatically by running `python cli.py setup`.

> Without installing the plugin, you can also give Claude this repo's link. `CLAUDE.md` tells it to clone the repo and follow the same flow.

**Requirements:** Python 3.9+ on the machine where Claude Code runs, with internet access to YouTube. The browser-only claude.ai chat can't download videos, so use Claude Code or the Code tab of the desktop app.

---

## 🌍 Dub reels into another language

Turn a Hindi stream into English reels, or an English stream into Hindi (also Tamil, Telugu, Bengali, Marathi, Spanish, ...):
1. `python cli.py dub-script URL --plan plan.json --lang hi` adds every spoken line (with times, from the captions) to each reel.
2. Translate the lines. In Claude this happens automatically: Claude translates meaning and slang, keeps lines short enough to fit, and writes native-script text for the voice plus Roman-script captions.
3. `python cli.py reel URL --plan plan.json` renders as usual, now dubbed:
   - **Voice:** free Microsoft neural voices via `edge-tts` (no account). Each line is fitted to the speaker's timing by speaking faster (and at most a small time-stretch).
   - **Background:** Demucs splits the original audio, keeps the game sound/music and the speaker's screams/laughs between lines, and removes his voice where the dub speaks. Without Demucs, the original is ducked under the dub.
   - **Captions** show the translated text.
   - **Lip-sync (optional):** `--lipsync sync` uses the sync.so cloud API (paid, set `SYNC_API_KEY`) to redraw the mouth for the new language. The default `none` keeps the original mouth movement.

`python cli.py voices` lists the default voices; any edge-tts voice works (`--voice hi-IN-SwaraNeural`).

---

## 📣 Post to YouTube Shorts and Instagram Reels

### Trending hashtags
`trends` reads YouTube search results for your topic filtered to **uploaded this week**, pulls the hashtags out of titles and descriptions, and ranks them by how many *different channels* use them on well-viewed fresh videos (one channel's own tag isn't a trend). Generic reach tags (#shorts, #viral...) are listed separately. With Instagram connected, `--ig-check 5` also checks the top tags for posts in the last 24 h (Instagram allows 30 hashtag lookups per week).

### Best time to post
`plan-posts` scores each reel (hook, length, captions, how strong the moment was, trend fit, how fresh the topic is) and gives it a slot per platform:
- Audience activity by hour in your audience's time zone. It starts from a general short-form baseline (gaming audiences skew later), then learns from **your** data once connected: how your own past posts did by posting hour, and Instagram's follower-online hours when available.
- The first 1-3 hours decide reach, so a slot is scored by activity over the 3 hours after posting (often 30-90 min before the peak).
- Hot topics (fresh source video, trending tags) are pulled earlier; the strongest reel gets the best slot; posts on one platform are spaced ~20 h apart.

Nothing can guarantee a reel goes viral; this puts the odds on your side.

### Connect your accounts (one time)
Credentials are stored in `%USERPROFILE%\.youtube-clipper\`, never in the repo.

**YouTube**
1. In [Google Cloud Console](https://console.cloud.google.com/) create a project and enable **YouTube Data API v3**.
2. Set up the **OAuth consent screen** (External, Testing) and add your Google account as a test user.
3. Create credentials, **OAuth client ID**, type **Desktop app**, and download the JSON.
4. Run `python cli.py connect youtube --client-secret path	o\client_secret.json` and sign in in the browser window that opens.

Google keeps videos uploaded from API projects that haven't passed the [YouTube API audit](https://support.google.com/youtube/contact/yt_api_form) **private**. Until yours passes, publish them from YouTube Studio (the tool warns you when this happens). The default API quota also limits how many uploads you can do per day.

**Instagram** (needs a Professional account: Business or Creator)
1. Switch Instagram to a Professional account, and link it to a Facebook Page (for the Facebook-login route).
2. At [developers.facebook.com](https://developers.facebook.com/) create an app with the Instagram API, and generate a token with the content-publishing permission (`instagram_content_publish`, or `instagram_business_content_publish` for Instagram login) plus basic/insights permissions.
3. Exchange it for a **long-lived token** (about 60 days) and run `python cli.py connect instagram --token <TOKEN>`. The account id is found automatically.

### Publish
`publish --dry-run` shows what goes where and when. Without `--dry-run`:
- **YouTube** reels are uploaded right away and YouTube publishes them at the planned time (`publishAt`), even if your PC is off.
- **Instagram** has no scheduling API, so reels are queued and posted by `post-due`. Keep `python cli.py runner --loop` open, or run `python cli.py runner --install` once to add a Windows scheduled task that checks every 10 minutes (`--uninstall` removes it). The PC must be on at posting time.

Always keep the credit and source link when posting someone else's content, and only post clips you have the rights to.

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
python cli.py context  URL --moments out/moments.json             # timed transcript around each moment
python cli.py frames   URL --start 5:18:00 --end 5:20:00          # contact sheet to see the screen layout
python cli.py reel     URL --plan out/plan.json --quality 1440 --out out/reels   # render vertical reels

python cli.py trends   --keywords "gta 6,mythpat"                  # hashtags trending this week
python cli.py best-times --platforms youtube,instagram --tz Asia/Kolkata
python cli.py plan-posts --plan out/plan.json --reels out/reels --url URL --moments out/moments.json --save out/posts.json
python cli.py connect  youtube --client-secret client_secret.json
python cli.py connect  instagram --token <LONG_LIVED_TOKEN>
python cli.py publish  --posts out/posts.json --dry-run           # then without --dry-run
python cli.py queue                                               # scheduled Instagram posts
python cli.py runner --loop                                       # posts queued reels on time (or --install)
```
`analyze` follows the conversation by default (`--min-len 20 --max-len 90`); add `--fixed` for exact `--length` clips. The reel plan format (layout, cam box, hook, cuts, captions) is documented at the top of `reel.py`.

Progress goes to stderr, and the result is JSON on stdout.

---

## How the best moments are found

| Signal | Source | Meaning |
|---|---|---|
| 🔁 Most replayed | YouTube's "Most replayed" heatmap | Where watch time and re-watching peak |
| 💬 Live chat | Live-chat replay of past streams (super chats count ×3) | Where chat exploded. Shifted 8 s earlier, because chat reacts late |
| 📝 Comment timestamps | Top ~1000 comments, e.g. "2:31:05 lmao", weighted by likes | Moments viewers point each other to |

Each signal is smoothed, normalised and combined. The top peaks are picked greedily, so clips **never overlap or repeat** and they respect the minimum gap.

**Context:** the video's captions (manual or YouTube auto-captions, in the original language) are split into utterances. Each clip starts at a natural pause before the setup and ends at a pause after the payoff, within the min/max length, and peaks that belong to the same story are merged into one clip. Without captions, clips fall back to the fixed length, starting ~40% before the peak. In Claude, the editor then reads the transcript to fine-tune every edge.

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
- `transcript.py`: captions, utterances, context-aware clip edges, caption chunks
- `reel.py`: 9:16 reel renderer (layouts, title card, captions, jump cuts, cold open)
- `dub.py`: translation dubbing (lines, AI voice, voice/music separation, mix)
- `lipsync.py`: optional lip-sync backends
- `trends.py`: hashtags trending this week
- `timing.py`: reel priority and best time to post
- `publish.py`: YouTube and Instagram sign-in, uploads, post queue
- `cli.py`: JSON command line used by Claude
- `app.py`, `templates/index.html`: web app
- `.claude-plugin/`, `skills/clip/SKILL.md`: Claude Code plugin and the guided clipping skill
- `CLAUDE.md`: instructions for Claude when the repo is cloned directly

MIT License.
