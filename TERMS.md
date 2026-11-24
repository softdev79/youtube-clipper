# Terms of use

Version 2026-11-24. These terms apply to everyone who runs YouTube Clipper (the plugin, the CLI or the web app).
The software is provided under the MIT License, "as is", without warranty (see [LICENSE](LICENSE)).

## 1. You need the rights to what you clip
- Only clip videos that you own, that are licensed for reuse (for example Creative Commons), or that you have the creator's written permission to clip and repost.
- Before the first download, the tool asks you to confirm this once (`python cli.py rights --accept`, or the checkbox in the web app). The confirmation stays on your computer.
- "Fair use" (US) and "fair dealing" (UK, India, Canada and others) are narrow, case-by-case defences, not permission. Reposting someone else's stream highlights to grow your own page usually doesn't qualify. If in doubt, ask the creator.
- Always credit the original creator. Credit doesn't replace permission.

## 2. Follow the platforms' rules
By using the YouTube features you agree to the [YouTube Terms of Service](https://www.youtube.com/t/terms), and [Google's Privacy Policy](https://policies.google.com/privacy) applies. Publishing to Instagram requires following [Instagram's Terms of Use](https://help.instagram.com/581066165581870) and [Meta's Platform Terms](https://developers.facebook.com/terms/). You are responsible for what you post, including YouTube's Community Guidelines, its reused-content policy, and its spam rules.

YouTube's Terms of Service don't allow downloading content without YouTube's permission or the rights holder's permission. Use the download features only for videos you own or have permission for (section 1).

## 3. AI-altered content must stay labelled
Dubbing replaces a real person's voice with an AI voice, and lip-sync changes their mouth movement. That makes the reel AI-altered ("synthetic") content. The tool labels it in three places: a small "AI-dubbed voice" line on the video, a sentence in the caption, and YouTube's "altered or synthetic content" setting. Don't remove these labels. Laws such as the EU AI Act (Article 50) and India's IT Rules (2026 amendment on synthetically generated information) require this kind of disclosure.

Never use dubbing to make someone appear to say something defamatory, sexual, political or misleading, or to impersonate them.

## 4. Your accounts and data
Your tokens and files stay on your computer (see [PRIVACY.md](PRIVACY.md)). You can revoke access at any time with `python cli.py accounts --disconnect youtube|instagram`, or delete everything with `python cli.py forget`.

## 5. No legal advice
These terms and [COMPLIANCE.md](COMPLIANCE.md) explain how the tool is built to help you comply. They aren't legal advice. Copyright, privacy and AI-labelling rules differ by country.
