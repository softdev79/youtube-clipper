---
name: clip
description: Create short clips from a YouTube video or past live stream at the moments with the most watch time, live-chat activity and comment mentions, many clips at once with no duplicates, and suggest hashtags. Use whenever the user shares a YouTube link and asks for clips, highlights, shorts, reels, best moments, or "use the youtube clipper".
---

# YouTube Clipper

This skill drives the YouTube Clipper engine, the same code the web app uses, so the clips are identical. The user should not need to open the web app or run commands. Ask your questions, run the CLI, and give the results here in the chat.

## 0. Locate the engine (do this silently)

`cli.py` sits at the plugin root, two folders above this SKILL.md. The skill's base directory is shown when it loads, so the CLI is at `<base dir>/../../cli.py`. Call that path `CLI` below and always quote it.
- Use `python` on Windows, or `python3` if `python` is missing.
- Set the Bash timeout to `600000` for every CLI call. Progress goes to stderr and the final result is JSON on stdout.
- **First use only.** If `python -c "import yt_dlp, flask, imageio_ffmpeg"` fails, run `python "CLI" setup` once. It installs the dependencies and bundles ffmpeg.

## 1. Get the link and check the video

If the user hasn't given a YouTube link yet, ask for it. Then run:

```
python "CLI" info "<URL>"
```

From the JSON, note `title`, `duration_hms`, `is_live`, `has_heatmap`, `has_chat` and `comment_count`.
- If `is_live` is true, stop. Tell the user the stream is still live and has no chat replay or Most-replayed data yet, and they should ask again after it ends.
- If `has_heatmap` and `has_chat` are both false and `comment_count` is small, warn the user that ranking will be weak. Continue anyway.

## 2. Ask the user what they want

Use the **AskUserQuestion** tool with these four questions in one call. Skip any the user already answered in their message, for example "give me 8 clips of 45 seconds".

1. **How many clips?** Header `Clips`. Options: `5`, `10 (Recommended)`, `15`, `20`. The user can type any number up to 50 via "Other".
2. **How long should each clip be?** Header `Length`. Options: `15 seconds`, `30 seconds (Recommended)`, `45 seconds`, `60 seconds`. Shorts and Reels work best at 60 seconds or less.
3. **Output format?** Header `Format`. Options: `MP4 720p (Recommended)`, `MP4 1080p`, `MP3 audio only`.
4. **Where will you post them (for hashtags)?** Header `Platform`. Options: `YouTube Shorts`, `Instagram Reels`, `TikTok`, `X / Twitter`.

Sanity-check the answers. If count × length is more than about 60% of the video's duration, tell the user that only fewer non-overlapping clips will fit, and continue.

## 3. Find the best moments

Write the output into the current working directory:

```
python "CLI" analyze "<URL>" --count <N> --length <SECONDS> --gap 15 --save "youtube-clips/<video_id>/moments.json"
```

- Pass `--sources` with only the signals that exist. The default `heatmap,chat,comments` is fine because missing signals are skipped and reported in `notes`.
- Long streams take 1 to 5 minutes, mostly to download the chat replay. Tell the user it's running.
- If fewer moments come back than requested, relay the note in `notes`.

Show the moments as a table, in time order, with these columns:
- rank
- start–end, using the `youtube_link` so each row is clickable
- score
- why: the chat message count, comment mentions, and one short sample quote

## 4. Cut the clips

Create every moment from the analysis without asking again:

```
python "CLI" clip "<URL>" --moments "youtube-clips/<video_id>/moments.json" --format <mp4|mp3> --quality <720|1080> --out "youtube-clips/<video_id>"
```

- If the user later wants only some of the moments, add `--pick 1,3,5`. For their own exact times, use `--ranges "1:02:10-1:02:40,..."` instead of `--moments`.
- Clips are made 2 at a time. Each takes roughly 5 to 20 seconds. Temporary YouTube 503 or 403 errors are retried automatically.
- The JSON includes `clips[]` with each `file`, plus `zip`, `created` and `failed`.

## 5. Hashtags

The analysis JSON already has `hashtags`. Its fields are `from_video` (the uploader's tags and description hashtags), `from_title`, `from_audience` (words the chat and comments repeated at these moments), `generic` and `all`.

Build the final suggestions for the platform the user picked:
1. Start from the most relevant `from_video`, `from_title` and `from_audience` tags. Drop vague ones.
2. If a web-search tool is available, search once for currently trending hashtags for this topic and platform, for example "trending hashtags <topic> <platform> <month year>". Add the 3 to 6 that genuinely fit. If no search tool is available, say these are based on the video and audience, not live trend data.
3. Give **one set of 15 to 20 hashtags for the whole video**, grouped as: Topic, Audience/moment, and Reach (for example #Shorts for YouTube Shorts or #Reels for Instagram).
4. For **each clip**, give a short catchy title (60 characters or fewer) and 3 to 5 hashtags. Base them on that clip's `chat_samples` and `comment_samples`, which tell you what happened at that moment.

Never invent view counts or claim a tag is "trending" unless you saw it in a search result.

## 6. Deliver

- Send the ZIP with the file-sending tool if one is available, for example SendUserFile. If none is available, give the full absolute path of the ZIP and of the folder.
- Show a final table with these columns: #, time range (linked), length, file name, title, hashtags.
- Give one line on any clips that failed and why.
- Offer short follow-ups: different length or count, MP3 versions, specific ranks only, or different times.

## Rules

- Never create overlapping or duplicate clips. The CLI enforces this. If the user gives ranges that overlap, ask them to adjust.
- Clips are limited to 50 per batch and 1 hour each.
- Only clip content the user has the right to use: their own videos, Creative Commons, or fair use.
- If downloads start failing in bulk, run `python -m pip install -U yt-dlp` and retry once, because YouTube changes often.
