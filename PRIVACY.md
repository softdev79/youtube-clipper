# Privacy policy

Version 2026-11-24. YouTube Clipper runs on your own computer. The author doesn't run a server, doesn't collect analytics and never receives your data.

## What is stored, and where
All of it is stored on your computer only:

| Data | Location | Why |
|---|---|---|
| YouTube OAuth client and token | `~/.youtube-clipper/youtube_client.json`, `youtube_token.json` | To upload to your channel and read your channel name and stats |
| Instagram token and account id | `~/.youtube-clipper/instagram.json` | To publish reels to your account |
| Post queue | `~/.youtube-clipper/queue.json` | Scheduled Instagram posts |
| Rights confirmation | `~/.youtube-clipper/rights.json` | Records that you confirmed you have the rights (version and time only) |
| Clips, reels, transcripts, moment lists | The output folder you choose, for example `./youtube-clips/` | Your work |

Set the `YTCLIPPER_HOME` environment variable to keep the settings folder somewhere else.

## What is sent where
- **YouTube / Google:** video pages, captions, live-chat replay and public comments are read to find the best moments, and video sections are downloaded (for videos you have the rights to). When you connect, sign-in goes through Google, and uploads use the YouTube Data API ([YouTube Terms](https://www.youtube.com/t/terms), [Google Privacy Policy](https://policies.google.com/privacy)). The tool asks only for `youtube.upload` and `youtube.readonly`.
- **Meta / Instagram:** only if you connect Instagram. Reels and captions go to the Instagram Graph API.
- **Microsoft (edge-tts):** only when you dub. The translated lines are sent to Microsoft's text-to-speech service to make the AI voice.
- **sync.so:** only if you choose `--lipsync sync` and set your own `SYNC_API_KEY`. The clip and voice track are sent to sync.so for lip-sync.
- Nothing else. Comment authors' names and the chat messages that are read are used only to score moments. They're saved in the moments file on your computer, never published, and you can delete them at any time.

## Your controls
- Revoke YouTube: `python cli.py accounts --disconnect youtube` (this also revokes the token with Google), or https://myaccount.google.com/permissions.
- Revoke Instagram: `python cli.py accounts --disconnect instagram`, then remove the app in Instagram, under Settings, then Apps and websites.
- Delete everything: `python cli.py forget --outputs youtube-clips clips` revokes both platforms and deletes the settings folder and the folders you list.
- Withdraw the rights confirmation: `python cli.py rights --withdraw`.

## Data from the YouTube API
Channel data the tool reads through the YouTube API, such as your channel name and subscriber count, is kept only inside your token file. It's removed when you disconnect, and it's refreshed every time you reconnect. Delete the tool's data within 30 days if you stop using it (`python cli.py forget`).

## Children
The tool isn't directed at children under 13, or under the minimum digital-consent age in your country.

## Contact
Open an issue at https://github.com/softdev79/youtube-clipper/issues.
