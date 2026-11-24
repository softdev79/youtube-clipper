# Compliance checklist

Status as of 2026-11-24. This list covers what the code does, and what the person publishing or selling the tool still has to do. It isn't legal advice.

## Built into the tool
| Requirement | Where it comes from | How the tool meets it |
|---|---|---|
| Uploads declare AI-altered content | YouTube "altered or synthetic content" policy; YouTube Data API `status.containsSyntheticMedia` | `plan-posts` marks dubbed reels `synthetic`, and `publish` sends `containsSyntheticMedia: true` |
| Visible AI disclosure on deepfake-like content | EU AI Act Art. 50(4) (deployers, since 2 Aug 2026); India IT Amendment Rules 2026 on synthetically generated information | "AI-dubbed voice" (or "& lip-sync") label in the reel header, plus an AI line in the YouTube description and Instagram caption |
| Made-for-kids declaration | YouTube / COPPA | `selfDeclaredMadeForKids` is always sent (default `false`). The user must change it for children's content |
| Users accept YouTube ToS; link to Google Privacy Policy | YouTube API Services Terms and Developer Policies | Shown at `connect youtube`, and in TERMS.md and PRIVACY.md |
| Privacy policy, revoke and delete | YouTube API Developer Policies; GDPR; India DPDP Act 2023 | PRIVACY.md; `accounts --disconnect` revokes the Google token at `oauth2.googleapis.com/revoke`; `forget` deletes all data |
| Minimum OAuth scopes | Google OAuth policy | Only `youtube.upload` and `youtube.readonly` |
| Rights confirmation before downloading | YouTube ToS (download only with permission); copyright law | `rights --accept` / web-app checkbox gate `clip`, `auto`, `frames` and `reel` |
| No posting without approval | Platform anti-spam rules | The skill requires a dry-run and an explicit yes for the exact post list |
| Data stays local | GDPR / DPDP data minimisation | No server, no analytics. Tokens are in `~/.youtube-clipper` |
| Third-party licenses | Open-source licenses | THIRD_PARTY_NOTICES.md; ffmpeg isn't committed |

## Blockers (cannot be fixed in code)

1. **Downloading from YouTube.** YouTube's Terms of Service don't allow downloading videos without YouTube's or the rights holder's permission, and yt-dlp-based tools aren't an approved method. The rights gate makes this lawful for creators clipping their own or permitted videos. A product whose main pitch is "clip anyone's stream" still conflicts with YouTube's terms, and a marketplace or YouTube can take it down. A safer product would also accept a local video file, or the creator's own uploads.
2. **Copyright in third-party streams.** Clipping another creator's stream, for example IShowSpeed, needs their permission. Credit and "fair use" don't protect monetised repost pages, so they collect Content ID claims and strikes. Users must clip their own or permitted content.
3. **"YouTube" in the product name.** The YouTube API Services Branding Guidelines prohibit "YouTube", "YT" or variants in an app's name. Descriptive wording such as "… for YouTube" is allowed. Rename the product before selling or listing it, for example to "Peak Clipper" or "StreamCut", and keep "for YouTube creators" in the description.
4. **YouTube API audit.** API projects created after 28 July 2020 that haven't passed YouTube's compliance audit can only upload private videos. Because each user brings their own Google Cloud OAuth client, each user's project needs an audit before uploads can be public. Otherwise they publish manually in YouTube Studio. To offer one-click public posting, the seller needs one audited Google project, a verified OAuth consent screen, and a hosted privacy policy URL.
5. **Instagram publishing.** It needs a Business or Creator account and a Meta app with `instagram_business_content_publish`. Any app used by other people needs Meta App Review and Business Verification.
6. **AI voice of a real person.** Dubbing a real streamer's voice can also touch their personality and publicity rights, for example the Indian court orders protecting celebrities' voices and likeness. Labels don't replace consent. Get the creator's OK for dubbed versions.
7. **Selling it (Agensi or any marketplace).**
   - The seller is responsible for tax on their earnings. In India, payouts in USDC (crypto) are treated as virtual digital assets for income tax, which is different from a normal export-of-services payment. Check this with a chartered accountant before listing a paid version.
   - The marketplace's terms apply, for example no links to paid versions sold elsewhere.
   - Agensi and other marketplaces may refuse tools that download from YouTube (blocker 1).

## Ongoing duties for whoever publishes reels
- Keep the AI labels on dubbed reels, and set "made for kids" correctly.
- Respond to copyright takedowns and remove reels when the creator asks.
- Re-check the policies above every few months, since YouTube, Meta, the EU and India update them often.
