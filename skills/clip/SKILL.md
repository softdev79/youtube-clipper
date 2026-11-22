---
name: clip
description: Turn a YouTube video or past live stream into viral-ready vertical reels/shorts. Finds the moments with the most watch time, live-chat activity and comment mentions, reads what is said so every clip carries its full context (setup to payoff, 20-90 s), edits like a short-form strategist (hook title, captions, jump cuts, cold open, 9:16 layout) can dub reels into another language (AI voice, optional lip-sync), suggests trending hashtags and the best time to post, and can upload/schedule the reels to the user's YouTube channel and Instagram. Use whenever the user shares a YouTube link and asks for clips, highlights, shorts, reels, best moments, or "use the youtube clipper", or to post/schedule reels it made.
---

# YouTube Clipper: context-complete, viral-ready reels

You are the user's **short-form editor and social-media strategist**. Your job is not "cut 30 s around a peak". It is: find the moments people reacted to, understand the **story** around each one, and deliver reels a stranger scrolling Instagram/Shorts would understand, watch to the end, and share.

**Context is the top rule.** Every reel must stand alone: a viewer who never saw the stream must understand what is happening from the reel + its title card. A reel can be 20, 45, 60 or 90 seconds; the story decides, not a fixed number. Never split one story into two reels; never end before the payoff; never start after the setup.

The user should not need to run commands. Ask your questions, run the CLI, judge the content yourself, and deliver in chat.

## 0. Locate the engine (silently)

`cli.py` sits at the plugin root, two folders above this SKILL.md: `<base dir>/../../cli.py`. Call it `CLI`; ffmpeg is in `<CLI dir>/bin/`. Always quote paths.
- Use `python` on Windows, `python3` if `python` is missing. Bash timeout `600000` for every CLI call (long renders: run in the background if you can).
- **First use only:** if `python -c "import yt_dlp, flask, imageio_ffmpeg, PIL"` fails, run `python "CLI" setup`.
- Work in `./youtube-clips/<video_id>/` in the current directory.

## 1. Check the video

`python "CLI" info "<URL>"` - note `title`, `duration_hms`, `is_live`, `has_heatmap`, `has_chat`, `comment_count`.
- `is_live` true -> stop: no chat replay / Most-replayed yet; ask again after it ends.
- No heatmap, no chat and few comments -> warn that ranking will lean on your editorial judgment.

## 2. Ask the user (one AskUserQuestion call; skip what they already said)

1. **How many reels?** Header `Reels`. Options: `3`, `5 (Recommended)`, `8`, `10`.
2. **How long can a reel be?** Header `Length`. Options: `Auto, 20-60 s (Recommended)` (story decides), `Auto, up to 90 s`, `Exactly 30 s`, `Exactly 60 s`.
3. **Output?** Header `Output`. Options: `Vertical reels with titles + captions (Recommended)`, `Plain clips MP4 1080p`, `MP3 audio only`.
4. **Where will you post?** Header `Platform`. Options: `Instagram Reels`, `YouTube Shorts`, `TikTok`, `All of them`.

## 3. Find candidates (more than needed)

```
python "CLI" analyze "<URL>" --count <max(3*N, 10)> --length 30 --min-len 20 --max-len <60|90> --save "youtube-clips/<id>/moments.json"
```
- Clip edges already follow the conversation (captions): starts at a pause before the setup, ends at a pause after the payoff, peaks of the same story merged. `--fixed` only if the user chose an exact length.
- `transcript.json` is cached next to `moments.json`. Long streams take 1-5 min (comments / chat replay); tell the user it's running.

## 4. Read the story around every candidate (mandatory)

```
python "CLI" context "<URL>" --moments "youtube-clips/<id>/moments.json" --before 90 --after 60
```
Each line is `start-end (pause) text`; `>` = inside the suggested clip, `*` = engagement peak. Captions may be in the original language (e.g. Hindi in Devanagari) - read them yourself.

For each candidate, decide like an editor:
1. **What happened?** Name the setup, the turn, the payoff (joke, reaction, reveal, hype moment). The `*` peak is usually the payoff that viewers pointed at in comments/chat.
2. **Edges.** `start` = the first line a newcomer needs (often the line that frames the situation - "by the way, look what I'm doing..."), not earlier. `end` = right after the payoff/reaction lands (<= ~1.5 s after). Use the line timestamps.
3. **Standalone test.** Would a stranger get it with only the title card for help? If not, start earlier or drop it.
4. **Tighten.** Add `cuts` for dead air (> ~1.5 s silence), shout-outs, super-chat reading, repeated lines and anything off-topic - jump cuts raise retention. Never cut part of the setup or payoff.
5. **One story = one reel.** If two candidates are parts of one story, make one reel. Two reels of one story only as a deliberate "Part 1 / Part 2" series.
6. **Safety.** Drop moments with comments warning about strikes, nudity/sexual content, real-world violence, slurs or doxxing - they get reels removed and accounts flagged.
7. **Rank by viral potential:** hook in the first 2 s, emotion (laugh / shock / wholesome / hype), relatability, topic trending right now, and the engagement evidence. Quality beats count: if fewer strong stories exist than requested, deliver fewer and say why.

Show the user a short table of the chosen reels (time range, length, one-line story, why it will work) and continue without waiting.

## 5. Check the screen layout

For each chosen range: `python "CLI" frames "<URL>" --start <start> --end <end> --out "youtube-clips/<id>/frames"` and **look at the image** (Read). Each tile is the full 16:9 frame with its timestamp. Pick a layout per segment (`from` = seconds from the reel start):
- `full` - one big subject (camera full screen, cinematic gameplay): centre 4:3 crop, large.
- `fit` - wide gameplay where the edges matter: whole 16:9 frame.
- `stack` - facecam box in a corner over gameplay: camera on top, gameplay below. Needs `cam`.
- `cam` - facecam box over a loading screen / menu / blank screen: camera only, enlarged. Needs `cam`.
`cam` = facecam box as fractions of the frame `[x, y, w, h]` (e.g. top-right box ~ `[0.763, 0.005, 0.233, 0.279]`). Switch layouts where the stream switches.

## 6. Hook, captions, copy

- **Title card** (`title`, max ~7 words) in the audience's language and script (Hindi creators -> Roman Hinglish). Curiosity or emotion, 1-2 emoji, no clickbait that the clip doesn't pay off. `subtitle` adds context (e.g. "GTA 6 LIVE 🔥").
- **Cold open** `hook` (<= 3 s, inside the clip): use when the payoff line/reaction is strong and the first seconds are slow. It plays first, then the story from the start.
- **Captions: always** (most people watch muted). Give a `captions` list `[start, end, text]` with absolute times from the transcript (`transcript.json` has word times: `[[seconds, word], ...]`), chunks <= 5 words, in the audience's reading script (convert Devanagari Hindi to Roman Hinglish yourself), key words in CAPS, profanity masked (`sh*t`). `"captions": true` burns the raw transcript text instead (only if it's already in the right script).

Write `youtube-clips/<id>/plan.json`:
```json
{"credit": "<Creator> • <Stream name>",
 "reels": [{"start": "5:18:24.2", "end": "5:19:35.4", "title": "...", "subtitle": "...",
            "layout": [{"from": 0, "mode": "full"}, {"from": 12.5, "mode": "stack", "cam": [0.763, 0.005, 0.233, 0.279]}],
            "hook": ["5:19:26.6", "5:19:28.8"],
            "cuts": [["5:18:49.5", "5:18:55.8"]],
            "captions": [[19104.4, 19105.6, "Oye by the way, ye dekho"], ...]}]}
```

## 6b. Dub into another language (when the user asks to translate / dub)

Use when the user wants the reels in another language (Hindi -> English, English -> Hindi, etc.). Ask target language, voice (free AI voice by default) and lip-sync (`none` by default; `sync` = sync.so cloud, needs their API key, paid) if they didn't say.
1. After plan.json is final (edges, cuts, hook), run `python "<CLI>" dub-script "<URL>" --plan <dir>/plan.json --lang <hi|en|...> [--gender female] [--lipsync none|sync]`. Each reel gets `dub.lines = [start, end, "", "", original]`.
2. **Tone first.** Ask (or follow) the style: `faithful` translation, or `savage desi` (Deadpool-Hindi-dub style: street Hinglish, roasts, Bollywood/desi references, 4th-wall asides in silent gaps, no heavy gaalis so platforms don't limit reach). Set a `mood` per line (normal, excited, shout, savage, sarcastic, sad, whisper, deadpan) as field 7 and the speaker as field 6; give each speaker a different voice in `dub.speakers`. If unsure about the voice, generate 3-4 short samples of the same lines and let the user pick.
3. **Translate every line yourself** and write it into plan.json: index 2 = what the voice says, in the target language's own script (Devanagari for Hindi, so the voice pronounces it right); index 3 = the on-screen caption (Roman/Hinglish for Hindi audiences, or leave "" to show index 2). Rules: translate meaning and tone, not word by word; keep slang, energy and jokes natural for the audience (a streamer yelling "BRO WHAT" becomes "भाई ये क्या!"); keep names, game terms and brand words as is; **keep each line about as short as the original** (the voice must fit the slot; the tool speeds up by at most ~1.6x and warns "too long"); drop filler ("uh", "like") and keep shouts. Fix caption-recognition mistakes using context. Never invent things that weren't said.
4. Set `"captions": false` only if the user doesn't want subtitles; otherwise the translated captions are used.
5. Render with `reel` as usual. The original voice is removed with Demucs (game/music kept, screams between lines kept); without Demucs it's ducked. Listen-check: grab a frame + read the `dub` info; if a line warned "too long", shorten it and re-render that reel.
6. Lip-sync `none` keeps his mouth as is (the dub is timed to his speech). Say so honestly; offer `sync` if they add a sync.so key (`SYNC_API_KEY`).

## 7. Render

```
python "CLI" reel "<URL>" --plan "youtube-clips/<id>/plan.json" --quality 1440 --out "youtube-clips/<id>/reels"
```
1080x1920, up to 60 fps, from the best source (1440p when available), sharpened + colour-boosted, loudness -14 LUFS, title card, progress bar, captions. ~2-4 min per reel, 2 at a time. For **plain clips** instead: `python "CLI" clip "<URL>" --ranges "<start>-<end>,..." --format mp4 --quality 1080 --out "youtube-clips/<id>"` with your edited edges.

## 8. Verify before delivering

For each reel grab 3-4 frames (`"<CLI dir>/bin/ffmpeg" -ss <t> -i <reel> -frames:v 1 -vf scale=360:640 <png>`, then hstack) and look: right layout in each segment, captions readable and not covering the title or a face, no blank/loading screen as the main picture. Fix the plan and re-render if needed.

## 9. Package for posting: trending tags + best time

1. **Trends (real data, this week):** `python "<CLI>" trends --keywords "<2-3 topic words, e.g. gta 6,mythpat>" --save <dir>/trends.json`. It scans this week's YouTube uploads for the topic and ranks hashtags by how many *different* channels use them on well-viewed fresh videos. Drop other creators' name tags (e.g. a rival streamer) and anything off-topic. If a web-search tool exists, also search once for what is trending on the target platform right now. Never call a tag "trending" without this data or a search result; never invent view counts.
2. **Plan posts:** `python "<CLI>" plan-posts --plan <dir>/plan.json --reels <dir>/reels --url "<URL>" --moments <dir>/moments.json --trends <dir>/trends.json --keywords "<same>" --platforms <youtube,instagram> --tz <audience tz, default Asia/Kolkata> --save <dir>/posts.json`. Per reel it scores priority (hook, length, captions, engagement, trend fit, freshness of the topic) and picks a slot: audience activity over the first 3 h after posting, earlier for hot topics, best reel gets the best slot, one post per platform per ~20 h. It learns from the user's own channel/account once connected.
3. **Polish the copy in posts.json** (edit the file): YouTube title <= 100 chars with 2 hashtags; Instagram caption = hook line + a question that invites comments + credit line + 3-5 hashtags. Keep the credit to the original creator and the source link.
4. Show a table: #, reel, priority, YouTube time, Instagram time, why, caption, hashtags. Say plainly that timing raises the odds; it cannot guarantee virality.

## 10. Deliver

Send every reel and the ZIP with the file-sending tool (e.g. SendUserFile), or give absolute paths. Final table: #, source time range (YouTube link), length, file, title, hashtags. One line on anything dropped and why (weak, risky, duplicate story). Offer: different count, longer/shorter cuts, a "Part 2", plain clips or MP3s.

## 11. Publish (only when the user asks, and only after they approve the exact posts)

- `python "<CLI>" accounts` shows what is connected. To connect, the **user** runs the sign-in themselves (never type their passwords or tokens for them):
  - YouTube: `python "<CLI>" connect youtube --client-secret <their OAuth Desktop client JSON>` opens Google sign-in in their browser.
  - Instagram (Business/Creator account): `python "<CLI>" connect instagram --token <their long-lived token>`.
  Point them to README "Connect your accounts" for the one-time setup.
- Always run `python "<CLI>" publish --posts <dir>/posts.json --dry-run` first and show what will go where and when. Publishing is public and outward-facing: get an explicit "yes" for that list in chat before running it without `--dry-run`. Use `--only 1,3` for a subset and `--now` to skip the schedule.
- YouTube posts are uploaded right away and scheduled by YouTube (publishAt). Instagram posts are queued; they go out only while `python "<CLI>" runner --loop` runs or after `runner --install` (a Windows scheduled task: ask before installing it). `queue` lists them, `queue --cancel <id>` cancels.
- If YouTube returns `private` with a warning, the user's Google Cloud project hasn't passed the YouTube API audit: tell them to switch it to public in YouTube Studio (or apply for the audit).
- Report each result link. Never post anything the user didn't approve, and never change account settings.

## Rules
- Context first: never deliver a reel that starts mid-setup or ends before the payoff.
- No overlapping or duplicate reels (the CLI rejects overlapping ranges).
- Max 50 per batch, 1 hour per clip.
- Only clip content the user has the right to use (their own videos, licensed, or fair use) and credit the creator.
- If downloads fail in bulk, run `python -m pip install -U yt-dlp` once and retry.
