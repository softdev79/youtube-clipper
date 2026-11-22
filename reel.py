"""
Vertical reel renderer (Instagram Reels / YouTube Shorts / TikTok): 1080x1920, up to 60 fps.

A reel spec (one entry of plan["reels"]):
{
  "start": "5:18:22", "end": "5:19:36",           # absolute times in the source video
  "title": "Bhai sink fix kar raha hai 😂",          # hook text on the title card (emoji OK)
  "subtitle": "GTA 6 LIVE 🔥",                      # optional 2nd line
  "layout": [{"from": 0, "mode": "full"},           # seconds from clip start; mode: full | fit | stack | stackfull | cam
                                                    # optional "game_crop": [top, bottom] to hide in-game subtitles
             {"from": 12, "mode": "stack", "cam": [0.763, 0.005, 0.233, 0.279]}],
                                                    # cam = facecam box as fractions [x, y, w, h]
  "hook": ["5:19:25", "5:19:28"],                   # optional cold open shown first (inside start-end)
  "captions": true,                                 # true = auto from transcript, false, or
                                                    # [["5:18:22.5", "5:18:24", "text"], ...]
  "music": true                                     # optional: generated lo-fi bed (or a file path), ducked under speech
}
plan = {"credit": "Mythpat • GTA 6 Launch Stream", "reels": [spec, ...]}
"""
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import clipper
from clipper import parse_time

W, H = 1080, 1920
# vertical bands: minimal header above TOP, video between TOP and BOT, subtitles in the blur below BOT
TOP, BOT = 400, 1580
CAM_H = 480                     # facecam height in stack modes
GAP = 0                         # facecam and game touch (a blurred seam showed as a coloured line)
CAP_Y = 1690                    # subtitle centre line (inside the clean blurred band)
FONTS = r"C:\Windows\Fonts" if os.name == "nt" else "/usr/share/fonts"


def _font(*names):
    for n in names:
        for base in (FONTS, "/Library/Fonts", "/System/Library/Fonts", "/usr/share/fonts/truetype/dejavu"):
            p = os.path.join(base, n)
            if os.path.exists(p):
                return p
    return None


F_BLACK = _font("seguibl.ttf", "Arial Black.ttf", "ariblk.ttf", "DejaVuSans-Bold.ttf")
F_BOLD = _font("segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf")
F_EMOJI = _font("seguiemj.ttf", "Apple Color Emoji.ttc", "NotoColorEmoji.ttf")
F_TITLE = _font("segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf")
F_SEMI = _font("seguisb.ttf", "segoeui.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans.ttf")
F_DEVA = _font("Nirmala.ttc", "Nirmala.ttf", "Kohinoor.ttc", "NotoSansDevanagari-Bold.ttf")
FFMPEG_EXE = os.path.join(clipper.FFMPEG, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")


# ---------------------------------------------------------------- title card (Pillow)
def _is_emoji(ch):
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or o in (0x2764, 0xFE0F, 0x200D)


def _runs(text):
    out, cur, emo = [], "", None
    for ch in text:
        e = _is_emoji(ch)
        if emo is None or e == emo:
            cur += ch
        else:
            out.append((cur, emo))
            cur = ch
        emo = e
    if cur:
        out.append((cur, emo))
    return out


def _fonts(size, face=None):
    fb = ImageFont.truetype(face or F_BLACK, size)
    fe = ImageFont.truetype(F_EMOJI, int(size * 0.9)) if F_EMOJI else fb
    return fb, fe


def _measure(text, size, face=None):
    fb, fe = _fonts(size, face)
    return sum((fe if e else fb).getlength(t) for t, e in _runs(text))


def _draw(d, x, y, text, size, fill, face=None):
    fb, fe = _fonts(size, face)
    for t, e in _runs(text):
        if e and F_EMOJI:
            d.text((x, y + size * 0.2), t, font=fe, embedded_color=True)
            x += fe.getlength(t)
        else:
            d.text((x, y), t, font=fb, fill=fill)
            x += fb.getlength(t)


def _wrap(text, size, maxw, face=None):
    lines, cur = [], ""
    words = []
    for w in text.split():                         # glue emoji-only tokens to the previous word (no orphans)
        if words and all(_is_emoji(c) for c in w):
            words[-1] += " " + w
        else:
            words.append(w)
    for w in words:
        test = (cur + " " + w).strip()
        if _measure(test, size, face) <= maxw or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _spaced(d, x, y, text, font, fill, track):
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + track


def title_card(path, title, subtitle="", credit="", top_y=None):
    """Minimal header: clean white title, soft subtitle and a small letter-spaced credit, no boxes.
    Sits in the blurred band above the video (y 130..TOP); a soft shadow keeps it readable."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    title = (title or "").replace("️", "")       # variation selectors render as blank gaps
    subtitle = (subtitle or "").replace("️", "")
    s1, maxw = 64, 900
    l1 = _wrap(title, s1, maxw, F_TITLE)
    while len(l1) > 2 and s1 > 48:
        s1 -= 4
        l1 = _wrap(title, s1, maxw, F_TITLE)
    h1 = int(s1 * 1.22)
    fcr = ImageFont.truetype(F_SEMI, 25)
    cr = credit.upper().replace("•", "·") if credit else ""
    track = 3
    crw = sum(fcr.getlength(c) + track for c in cr) - track if cr else 0
    sub = re.sub(r"\s+", " ", subtitle or "").strip()
    block = (56 if cr else 0) + h1 * len(l1) + (58 if sub else 0)
    y = top_y if top_y is not None else int(130 + (TOP - 40 - 130 - block) / 2)
    if cr:                                        # small letter-spaced credit + hairline
        _spaced(d, (W - crw) / 2, y, cr, fcr, (255, 255, 255, 150), track)
        y += 34
        d.line([(W / 2 - 24, y + 4), (W / 2 + 24, y + 4)], fill=(255, 255, 255, 110), width=2)
        y += 22
    for line in l1:
        _draw(d, (W - _measure(line, s1, F_TITLE)) / 2, y, line, s1, (255, 255, 255, 255), F_TITLE)
        y += h1
    if sub:
        y += 14
        _draw(d, (W - _measure(sub, 36, F_SEMI)) / 2, y, sub, 36, (255, 255, 255, 185), F_SEMI)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(txt.getchannel("A").point(lambda a: int(a * 0.55)))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)), (0, 3))
    img.alpha_composite(txt)
    img.save(path)


# ---------------------------------------------------------------- filter graph
def _probe(path):
    r = subprocess.run([FFMPEG_EXE, "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", r.stderr)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", r.stderr)
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return (int(m.group(1)), int(m.group(2)), float(fps.group(1)) if fps else 30.0,
            int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)))


def _even(x):
    return max(2, int(round(x / 2)) * 2)


ENH = "cas=strength=0.55,eq=contrast=1.06:saturation=1.18:brightness=0.01"


def _fit_cam(cam, sw, sh, ar):
    """facecam box -> crop (x, y, w, h) trimmed to aspect ratio ar (w/h)"""
    cx, cy, cw, chh = cam[0] * sw, cam[1] * sh, cam[2] * sw, cam[3] * sh
    if cw / chh > ar:
        nw = chh * ar
        cx, cw = cx + (cw - nw) / 2, nw
    else:
        nh = cw / ar
        cy, chh = cy + (chh - nh) / 2, nh
    return cx, cy, cw, chh


def _scale_fit(w_in, h_in, max_h):
    """scale to full width; if taller than max_h, centre-crop the height. Returns (filter, out_h)."""
    nat = _even(W * h_in / w_in)
    if nat > max_h:
        return f"scale={W}:{nat}:flags=lanczos,crop={W}:{_even(max_h)}", _even(max_h)
    return f"scale={W}:{nat}:flags=lanczos", nat


def _layers(mode, cam, sw, sh, src, k, game_crop=None):
    """Return (filter strings, [(label, x, y)]) for one layout mode.
    All video stays between TOP and BOT so the header and subtitles sit on clean blur, never on the picture.
    game_crop = [top, bottom] fractions of the game picture to drop (e.g. [0, 0.12] hides in-game subtitles)."""
    f, out = [], []
    gt, gb = (game_crop or [0, 0])[:2]
    gy0, gsh = int(sh * gt), _even(sh * (1 - gt - gb))
    room = BOT - TOP
    if mode == "fit":
        sc, oh = _scale_fit(sw, gsh, room)
        f.append(f"[{src}]crop={sw}:{gsh}:0:{gy0},{sc},{ENH}[f{k}]")
        out.append((f"f{k}", 0, TOP + (room - oh) // 2))
    elif mode == "cam" and cam:                   # facecam only, enlarged (e.g. over loading screens)
        cx, cy, cw, chh = cam[0] * sw, cam[1] * sh, cam[2] * sw, cam[3] * sh
        sc, oh = _scale_fit(cw, chh, room)
        f.append(f"[{src}]crop={_even(cw)}:{_even(chh)}:{int(cx)}:{int(cy)},split=2[{src}c][{src}d]")
        # blurred background from the camera itself (the rest of the frame is a menu/loading screen)
        f.append(f"[{src}d]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                 f"gblur=sigma=38,eq=brightness=-0.22:saturation=1.25[cb{k}]")
        f.append(f"[{src}c]{sc},{ENH}[f{k}]")
        out += [(f"cb{k}", 0, 0), (f"f{k}", 0, TOP + (room - oh) // 2)]
    elif mode in ("stack", "stackfull") and cam:  # facecam on top, game below
        cx, cy, cw, chh = _fit_cam(cam, sw, sh, W / CAM_H)
        f.append(f"[{src}]split=2[{src}a][{src}b]")
        f.append(f"[{src}a]crop={_even(cw)}:{_even(chh)}:{int(cx)}:{int(cy)},"
                 f"scale={W}:{CAM_H}:flags=lanczos,{ENH}[c{k}]")
        gy = TOP + CAM_H + GAP
        if mode == "stackfull":                   # the whole game frame (menus, HUD)
            gx0, gw = 0, sw
        else:                                     # game area beside the facecam, else a centre 4:3 crop
            camx0, camx1 = cam[0] * sw, (cam[0] + cam[2]) * sw
            gx0, gx1 = (0, camx0) if (camx0 + camx1) / 2 > sw / 2 else (camx1, sw)
            if gx1 - gx0 < 1.2 * sh:
                gx0, gx1 = (sw - sh * 4 / 3) / 2, (sw + sh * 4 / 3) / 2
            gw = gx1 - gx0
        sc, _ = _scale_fit(gw, gsh, BOT - gy)
        f.append(f"[{src}b]crop={_even(gw)}:{gsh}:{int(gx0)}:{gy0},{sc},{ENH}[g{k}]")
        out += [(f"c{k}", 0, TOP), (f"g{k}", 0, gy)]
    else:                                         # full: centre 4:3 crop, big
        cw = min(sw, gsh * 4 / 3)
        sc, oh = _scale_fit(cw, gsh, room)
        f.append(f"[{src}]crop={_even(cw)}:{gsh}:{int((sw - cw) / 2)}:{gy0},{sc},{ENH}[f{k}]")
        out.append((f"f{k}", 0, TOP + (room - oh) // 2))
    return f, out

def _esc_path(p):
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render(src, out, spec, words=None, credit="", tmp=None, log=print, music=None):
    tmp = tmp or tempfile.mkdtemp(prefix="reel_")
    sw, sh, fps, src_dur = _probe(src)
    fps = min(60, round(fps))
    start, end = parse_time(spec["start"]), parse_time(spec["end"])
    dur = min(end - start, src_dur)
    hook = spec.get("hook")
    hs = he = 0.0
    if hook:
        hs, he = parse_time(hook[0]) - start, parse_time(hook[1]) - start
        if not (0 <= hs < he <= dur) or he - hs > 5:
            log("  hook ignored (must be inside the clip and at most 5 s)")
            hook = None
    hl = (he - hs) if hook else 0.0
    # jump cuts: remove dead air / off-topic bits inside the clip (absolute [a, b] ranges)
    kept, pos = [], 0.0
    for c in sorted(spec.get("cuts") or [], key=lambda c: parse_time(c[0])):
        a, b = parse_time(c[0]) - start, parse_time(c[1]) - start
        a, b = max(0.0, a), min(dur, b)
        if b - a < 0.2 or a < pos:
            continue
        if a > pos:
            kept.append((pos, a))
        pos = b
    if pos < dur:
        kept.append((pos, dur))
    body = sum(b - a for a, b in kept)
    total = hl + body

    def out_t(t):
        """source-relative time -> output time (None if cut away)"""
        acc = hl
        for a, b in kept:
            if a <= t < b:
                return acc + (t - a)
            acc += b - a
        return None

    png = os.path.join(tmp, "title.png")
    title_card(png, spec.get("title", ""), spec.get("subtitle", ""), credit)

    layout = sorted(spec.get("layout") or [{"from": 0, "mode": "full"}], key=lambda s: s.get("from", 0))
    fg = [f"[0:v]split={1 + len(layout)}[bgsrc]" + "".join(f"[s{i}]" for i in range(len(layout))),
          f"[bgsrc]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"gblur=sigma=42,eq=brightness=-0.22:saturation=1.25,fps={fps}[base0]"]
    cur = "base0"
    for i, seg in enumerate(layout):
        a = float(seg.get("from", 0))
        b = float(layout[i + 1]["from"]) if i + 1 < len(layout) else 1e9
        en = f"enable='between(t,{a:.3f},{b:.3f})'" if len(layout) > 1 else ""
        fl, outs = _layers(seg.get("mode", "full"), seg.get("cam"), sw, sh, f"s{i}", i, seg.get("game_crop"))
        fg += fl
        for j, (lab, x, y) in enumerate(outs):
            nxt = f"b{i}_{j}"
            fg.append(f"[{cur}][{lab}]overlay={x}:{y}" + (f":{en}" if en else "") + f"[{nxt}]")
            cur = nxt

    # cold-open hook + kept body segments, joined with concat
    segs = ([(hs, he)] if hook else []) + kept
    n = len(segs)
    if n == 1:
        a, b = segs[0]
        fg.append(f"[{cur}]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[vc]")
        fg.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[ac]")
    else:
        # Audio is cut in its own audio-only pass. Splitting it inside the heavy video graph made
        # ffmpeg drop queued audio frames, and concat padded the hole with silence (20 s+ gaps).
        ag = [f"[0:a]asplit={n}" + "".join(f"[as{i}]" for i in range(n))]
        apairs = ""
        for i, (a, b) in enumerate(segs):
            ag.append(f"[as{i}]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d=0.03,afade=t=out:st={max(0, b - a - 0.03):.3f}:d=0.03[at{i}]")
            apairs += f"[at{i}]"
        ag.append(f"{apairs}concat=n={n}:v=0:a=1[ac]")
        audio_wav = os.path.join(tmp, "audio.wav")
        r = subprocess.run([FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vn",
                            "-filter_complex", ";".join(ag), "-map", "[ac]", "-c:a", "pcm_s16le", audio_wav],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            raise RuntimeError("ffmpeg audio cut failed: " + r.stderr[-1500:])
        fg.append(f"[{cur}]split={n}" + "".join(f"[vs{i}]" for i in range(n)))
        pairs = ""
        for i, (a, b) in enumerate(segs):
            fg.append(f"[vs{i}]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[vt{i}]")
            pairs += f"[vt{i}]"
        fg.append(f"{pairs}concat=n={n}:v=1:a=0[vc]")
        fg.append("[2:a]anull[ac]")
    vlab, alab = "vc", "ac"

    fg += [f"[{vlab}][1:v]overlay=0:0:shortest=1[t0]",
           f"color=c=white@0.7:s={W}x5:r={fps},format=rgba[bar]",
           f"[t0][bar]overlay=x='-{W}+{W}*t/{total:.3f}':y=0:shortest=1[t1]"]
    cur = "t1"

    # captions
    src_caps = []                                  # (source-relative start, end, text)
    cs = spec.get("captions", False)
    if cs is True and words:
        from transcript import chunk_captions
        src_caps = [(s - start, e - start, t) for s, e, t in chunk_captions(words, start, start + dur)]
    elif isinstance(cs, list):
        src_caps = [(parse_time(c[0]) - start, parse_time(c[1]) - start, c[2]) for c in cs]
    caps = []
    for s, e, t in src_caps:
        o = out_t(s)
        if o is None:
            continue
        seg_end = next((hl + sum(b - a for a, b in kept[:i + 1]) for i, (a, b) in enumerate(kept) if a <= s < b), total)
        caps.append((o, min(o + (e - s), seg_end), t))
        if hook and hs <= s < he:
            caps.append((s - hs, min(e, he) - hs, t))
    caps.sort()
    caps = [(a, min(b, caps[i + 1][0]) if i + 1 < len(caps) else b, t) for i, (a, b, t) in enumerate(caps)]

    for n, (a, b, text) in enumerate(caps):
        if b - a < 0.1 or a >= total:
            continue
        text = text.strip()
        if len(text) > 26:                          # wrap into two balanced lines
            ws = text.split()
            best = min(range(1, len(ws)), key=lambda i: abs(len(" ".join(ws[:i])) - len(" ".join(ws[i:]))),
                       default=0)
            if best:
                text = " ".join(ws[:best]) + "\n" + " ".join(ws[best:])
        tf = os.path.join(tmp, f"cap_{n:03d}.txt")
        with open(tf, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        deva = bool(re.search(r"[\u0900-\u097F]", text))
        font = F_DEVA if (deva and F_DEVA) else F_TITLE
        longest = max(len(x) for x in text.split("\n"))
        size = max(50, min(62, int(62 * 24 / max(24, longest))))
        nxt = f"cap{n}"
        fg.append(f"[{cur}]drawtext=fontfile='{_esc_path(font)}':textfile='{_esc_path(tf)}':"
                  f"fontsize={size}:fontcolor=white:borderw=2:bordercolor=black@0.35:line_spacing=10:"
                  f"text_align=center:shadowx=0:shadowy=3:shadowcolor=black@0.45:"
                  f"x=(w-text_w)/2:y={CAP_Y}-text_h/2:"
                  f"enable='gte(t,{max(0, a):.3f})*lt(t,{b:.3f})'[{nxt}]")
        cur = nxt

    fg.append(f"[{cur}]fps={fps},setsar=1,format=yuv420p[v]")
    music = music or spec.get("music")
    extra = ["-i", os.path.join(tmp, "audio.wav")] if len(segs) > 1 else []
    if music:                                     # soft music bed, ducked under the streamer's voice
        if music is True or music == "auto":
            import music as music_mod
            music = music_mod.generate(os.path.join(tmp, "music.wav"), total + 1, seed=spec.get("title", ""))
        mi = 2 + (1 if extra else 0)
        extra += ["-i", music]
        fg += [f"[{alab}]asplit=2[sp][key]",
               f"[{mi}:a]aresample=48000,volume={float(spec.get('music_volume', 0.30)):.2f},"
               f"atrim=0:{total:.3f}[mus]",
               "[mus][key]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=450[duck]",
               "[sp][duck]amix=inputs=2:normalize=0:duration=first[mix]"]
        alab = "mix"
    fg.append(f"[{alab}]loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.05,"
              f"afade=t=out:st={max(0, total - 0.4):.3f}:d=0.4,aresample=48000[a]")
    script = os.path.join(tmp, "graph.txt")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(fg))
    cmd =[FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-loop", "1", "-i", png, *extra,
           "-/filter_complex", script, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-level", "4.2",
           "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-1500:])
    return {"file": out, "seconds": round(total, 2), "captions": len(caps), "hook": bool(hook)}


def slug(text, n=40):
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return (s[:n].strip("-") or "reel")


def contact_sheet(src, out, offset=0.0, every=None, cols=4, rows=3):
    """Grid of frames with absolute timestamps, so Claude/users can see the on-screen layout."""
    _sw, _sh, _fps, d = _probe(src)
    every = every or max(1.0, d / (cols * rows))
    vf = (f"fps=1/{every:.3f},scale=480:-2,drawtext=fontfile='{_esc_path(F_BOLD)}':"
          f"text='%{{pts\\:hms\\:{offset:.3f}}}':x=6:y=6:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.7,"
          f"tile={cols}x{rows}")
    r = subprocess.run([FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", vf,
                        "-frames:v", "1", out], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return out
