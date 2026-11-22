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
  "captions": true                                  # true = auto from transcript, false, or
                                                    # [["5:18:22.5", "5:18:24", "text"], ...]
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


def _fonts(size):
    fb = ImageFont.truetype(F_BLACK, size)
    fe = ImageFont.truetype(F_EMOJI, int(size * 0.9)) if F_EMOJI else fb
    return fb, fe


def _measure(text, size):
    fb, fe = _fonts(size)
    return sum((fe if e else fb).getlength(t) for t, e in _runs(text))


def _draw(d, x, y, text, size, fill):
    fb, fe = _fonts(size)
    for t, e in _runs(text):
        if e and F_EMOJI:
            d.text((x, y + size * 0.2), t, font=fe, embedded_color=True)
            x += fe.getlength(t)
        else:
            d.text((x, y), t, font=fb, fill=fill)
            x += fb.getlength(t)


def _wrap(text, size, maxw):
    lines, cur = [], ""
    for w in text.split():
        test = (cur + " " + w).strip()
        if _measure(test, size) <= maxw or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def title_card(path, title, subtitle="", credit="", top_y=150):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s1, s2, maxw = 86, 62, 940
    l1 = _wrap(title, s1, maxw)
    while len(l1) > 2 and s1 > 58:
        s1 -= 6
        l1 = _wrap(title, s1, maxw)
    l2 = _wrap(subtitle, s2, maxw) if subtitle else []
    h1, h2 = int(s1 * 1.18), int(s2 * 1.2)
    ch = 50 + h1 * len(l1) + (h2 * len(l2) + 14 if l2 else 0) + 40
    cw = int(max([_measure(x, s1) for x in l1] + [_measure(x, s2) for x in l2]) + 90)
    x0 = (W - cw) // 2
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0 + 8, top_y + 14, x0 + cw + 8, top_y + ch + 14], 38,
                                         fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, top_y, x0 + cw, top_y + ch], 38, fill=(255, 255, 255, 245))
    for i in range(cw - 76):                      # pink -> cyan accent bar
        t = i / max(1, cw - 77)
        d.line([(x0 + 38 + i, top_y + ch - 16), (x0 + 38 + i, top_y + ch - 8)],
               fill=(int(255 * (1 - t)), int(46 + 178 * t), int(160 + 95 * t), 255))
    y = top_y + 38
    for line in l1:
        _draw(d, (W - _measure(line, s1)) / 2, y, line, s1, (15, 15, 20))
        y += h1
    if l2:
        y += 6
        for line in l2:
            _draw(d, (W - _measure(line, s2)) / 2, y, line, s2, (255, 46, 140))
            y += h2
    if credit:
        fs = ImageFont.truetype(F_BOLD, 40)
        tw = fs.getlength(credit)
        px, py = (W - tw - 60) / 2, top_y + ch + 36
        d.rounded_rectangle([px, py, px + tw + 60, py + 66], 33, fill=(0, 0, 0, 170))
        d.text((px + 30, py + 9), credit, font=fs, fill=(255, 255, 255))
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


def _layers(mode, cam, sw, sh, src, k, game_crop=None):
    """Return (filter strings, [(label, x, y)]) for one layout mode.
    game_crop = [top, bottom] fractions of the game picture to drop (e.g. [0, 0.12] hides in-game subtitles)."""
    f, out = [], []
    gt, gb = (game_crop or [0, 0])[:2]
    gy0, gsh = int(sh * gt), _even(sh * (1 - gt - gb))
    if mode == "fit":
        oh = _even(W * sh / sw)
        f.append(f"[{src}]scale={W}:{oh}:flags=lanczos,{ENH}[f{k}]")
        out.append((f"f{k}", 0, (H - oh) // 2))
    elif mode == "cam" and cam:                   # facecam only, enlarged (e.g. over loading screens)
        cx, cy, cw, chh = cam[0] * sw, cam[1] * sh, cam[2] * sw, cam[3] * sh
        oh = min(_even(W * chh / cw), 1100)
        f.append(f"[{src}]crop={_even(cw)}:{_even(chh)}:{int(cx)}:{int(cy)},split=2[{src}c][{src}d]")
        # blurred background from the camera itself (the rest of the frame is a menu/loading screen)
        f.append(f"[{src}d]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                 f"gblur=sigma=38,eq=brightness=-0.13:saturation=1.35[cb{k}]")
        f.append(f"[{src}c]scale={W}:{oh}:flags=lanczos,{ENH}[f{k}]")
        out += [(f"cb{k}", 0, 0), (f"f{k}", 0, 640)]
    elif mode == "stackfull" and cam:              # facecam on top, the whole game frame below (menus, HUD)
        cx, cy, cw, chh = cam[0] * sw, cam[1] * sh, cam[2] * sw, cam[3] * sh
        ar = W / 560
        if cw / chh > ar:
            nw = chh * ar
            cx, cw = cx + (cw - nw) / 2, nw
        else:
            nh = cw / ar
            cy, chh = cy + (chh - nh) / 2, nh
        gh = _even(W * gsh / sw)
        f.append(f"[{src}]split=2[{src}a][{src}b]")
        f.append(f"[{src}a]crop={_even(cw)}:{_even(chh)}:{int(cx)}:{int(cy)},"
                 f"scale={W}:560:flags=lanczos,{ENH}[c{k}]")
        f.append(f"[{src}b]crop={sw}:{gsh}:0:{gy0},scale={W}:{gh}:flags=lanczos,{ENH}[g{k}]")
        out += [(f"c{k}", 0, 552), (f"g{k}", 0, 1112)]
    elif mode == "stack" and cam:
        cx, cy, cw, chh = cam[0] * sw, cam[1] * sh, cam[2] * sw, cam[3] * sh
        ar = W / 560
        if cw / chh > ar:
            nw = chh * ar
            cx, cw = cx + (cw - nw) / 2, nw
        else:
            nh = cw / ar
            cy, chh = cy + (chh - nh) / 2, nh
        f.append(f"[{src}]split=2[{src}a][{src}b]")
        f.append(f"[{src}a]crop={_even(cw)}:{_even(chh)}:{int(cx)}:{int(cy)},"
                 f"scale={W}:560:flags=lanczos,{ENH}[c{k}]")
        camx0, camx1 = cam[0] * sw, (cam[0] + cam[2]) * sw
        gx0, gx1 = (0, camx0) if (camx0 + camx1) / 2 > sw / 2 else (camx1, sw)
        if gx1 - gx0 < 1.2 * sh:                  # too narrow -> centre 4:3 crop
            gx0, gx1 = (sw - sh * 4 / 3) / 2, (sw + sh * 4 / 3) / 2
        gw = gx1 - gx0
        gh_out = _even(W * gsh / gw)
        crop_v = ""
        if gh_out > 808:
            crop_v = f",crop={W}:808"
            gh_out = 808
        f.append(f"[{src}b]crop={_even(gw)}:{gsh}:{int(gx0)}:{gy0},scale={W}:{_even(W * gsh / gw)}:flags=lanczos"
                 f"{crop_v},{ENH}[g{k}]")
        out += [(f"c{k}", 0, 552), (f"g{k}", 0, 1112)]
    else:                                         # full: centre 4:3 crop, big
        cw = min(sw, sh * 4 / 3)
        f.append(f"[{src}]crop={_even(cw)}:{sh}:{int((sw - cw) / 2)}:0,scale={W}:810:flags=lanczos,{ENH}[f{k}]")
        out.append((f"f{k}", 0, 640))
    return f, out


def _esc_path(p):
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render(src, out, spec, words=None, credit="", tmp=None, log=print):
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
          f"gblur=sigma=38,eq=brightness=-0.13:saturation=1.35,fps={fps}[base0]"]
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
            flash = ",fade=in:st=0:d=0.25:color=white" if hook and i == 1 else ""
            fg.append(f"[vs{i}]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS{flash}[vt{i}]")
            pairs += f"[vt{i}]"
        fg.append(f"{pairs}concat=n={n}:v=1:a=0[vc]")
        fg.append("[2:a]anull[ac]")
    vlab, alab = "vc", "ac"

    fg += [f"[{vlab}][1:v]overlay=0:0:shortest=1[t0]",
           f"color=c=0xFF2E8C:s={W}x12:r={fps},format=rgba[bar]",
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
        if len(text) > 22:                          # wrap into two balanced lines
            ws = text.split()
            best = min(range(1, len(ws)), key=lambda i: abs(len(" ".join(ws[:i])) - len(" ".join(ws[i:]))),
                       default=0)
            if best:
                text = " ".join(ws[:best]) + "\n" + " ".join(ws[best:])
        tf = os.path.join(tmp, f"cap_{n:03d}.txt")
        with open(tf, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        deva = bool(re.search(r"[\u0900-\u097F]", text))
        font = F_DEVA if (deva and F_DEVA) else F_BLACK
        longest = max(len(x) for x in text.split("\n"))
        size = max(54, min(76, int(76 * 20 / max(20, longest))))
        nxt = f"cap{n}"
        fg.append(f"[{cur}]drawtext=fontfile='{_esc_path(font)}':textfile='{_esc_path(tf)}':"
                  f"fontsize={size}:fontcolor=white:borderw=8:bordercolor=black@0.95:line_spacing=6:"
                  f"text_align=center:shadowx=0:shadowy=4:shadowcolor=black@0.6:"
                  f"x=(w-text_w)/2:y=1330-text_h/2:"
                  f"enable='gte(t,{max(0, a):.3f})*lt(t,{b:.3f})'[{nxt}]")
        cur = nxt

    fg.append(f"[{cur}]fps={fps},setsar=1,format=yuv420p[v]")
    fg.append(f"[{alab}]loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.05,"
              f"afade=t=out:st={max(0, total - 0.4):.3f}:d=0.4,aresample=48000[a]")
    script = os.path.join(tmp, "graph.txt")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(fg))
    extra = ["-i", os.path.join(tmp, "audio.wav")] if len(segs) > 1 else []
    cmd = [FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-loop", "1", "-i", png, *extra,
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
