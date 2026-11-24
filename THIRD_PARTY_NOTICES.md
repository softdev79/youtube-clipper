# Third-party notices

YouTube Clipper is MIT-licensed. It doesn't bundle third-party code in the repository. The packages below are installed by `pip` (`python cli.py setup`) from their official sources, under their own licenses:

| Package | Used for | License |
|---|---|---|
| yt-dlp | Reading video info, captions, chat replay and comments, and downloading sections | Unlicense (public domain) |
| imageio-ffmpeg | Provides an ffmpeg binary | Wrapper: BSD-2-Clause. The ffmpeg binary it downloads is a GPL build, see https://ffmpeg.org/legal.html |
| Flask | Web app | BSD-3-Clause |
| Pillow | Title cards, frames | MIT-CMU (HPND) |
| requests | API calls | Apache-2.0 |
| numpy | Generated background music | BSD-3-Clause |
| tzdata | Time zones for scheduling | Apache-2.0 |
| edge-tts | AI voice for dubbing (Microsoft Edge online TTS) | LGPL-3.0 |
| demucs (optional) | Voice/music separation | MIT |

Notes for anyone redistributing:
- If you ship a copy that includes `ffmpeg.exe` (for example in a ZIP or installer), you must follow ffmpeg's license: include the license text, say which build it is, and offer its source code. The repository itself doesn't include ffmpeg (`bin/` is git-ignored).
- Fonts: the renderer uses fonts already installed on your system (Segoe UI on Windows, DejaVu or Noto on Linux, Arial or Apple fonts on macOS). It doesn't ship any font files.
- The background music is generated from code at render time (`music.py`). There are no samples and no third-party recordings.
- Check each project's upstream license before you redistribute it. This table is a summary.
