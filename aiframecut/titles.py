"""PIL-based rendering: labeled contact sheets and animated title/intro/outro cards."""
from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from ._ffmpeg import ffmpeg, fmt_tc


# ---------------------------------------------------------------- fonts ----
def find_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    cands: list[str] = []
    if os.name == "nt":
        b = r"C:\Windows\Fonts"
        cands += [rf"{b}\bahnschrift.ttf",
                  rf"{b}\arialbd.ttf" if bold else rf"{b}\arial.ttf",
                  rf"{b}\segoeui.ttf"]
    cands += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in cands:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _text_w(draw, text, font) -> float:
    return draw.textlength(text, font=font)


def _draw_tracked(draw, xy, text, font, fill, tracking):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def _tracked_width(draw, text, font, tracking) -> float:
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * max(0, len(text) - 1)


# -------------------------------------------------------- contact sheet ----
def build_contact_sheet(frames: list[Path], out: str, cols: int,
                        start: float, interval: float, gap: int = 6) -> str:
    """Tile frame images into a labeled grid (timecode stamped on each cell)."""
    if not frames:
        raise SystemExit("[aiframecut] no frames were extracted for the contact sheet.")
    thumbs = [Image.open(f).convert("RGB") for f in frames]
    tw, th = thumbs[0].size
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * gap,
                              rows * th + (rows + 1) * gap), (17, 17, 20))
    font = find_font(max(13, tw // 20), bold=True)
    draw = ImageDraw.Draw(sheet)
    for i, im in enumerate(thumbs):
        r, c = divmod(i, cols)
        x = gap + c * (tw + gap)
        y = gap + r * (th + gap)
        sheet.paste(im, (x, y))
        label = fmt_tc(start + i * interval)
        pad = 4
        lw = draw.textlength(label, font=font)
        draw.rectangle([x, y, x + lw + pad * 2, y + font.size + pad * 2], fill=(0, 0, 0))
        draw.text((x + pad, y + pad), label, font=font, fill=(255, 220, 120))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


# ----------------------------------------------------------- title card ----
_STYLES = {
    # glow_rgb, flicker(bool), grain
    "horror": ((205, 32, 32), True, 7),
    "clean":  ((70, 90, 130), False, 3),
    "glitch": ((40, 200, 210), True, 6),
    "warm":   ((210, 120, 40), False, 4),
}


def _make_assets(text: str, sub: str, size: tuple[int, int], style: str, tmp: Path,
                 logo: str | None = None, cta: str | None = None):
    W, H = size
    glow_rgb, _, _ = _STYLES.get(style, _STYLES["horror"])
    scale = H / 1080.0

    # background: near-black + radial glow + vignette + faint scanlines
    bg = Image.new("RGB", (W, H), (5, 5, 8))
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    cx, cy = W // 2, int(H * 0.46)
    maxr = int(640 * scale)
    for r in range(maxr, 0, -3):
        gd.ellipse([cx - r, cy - int(r * 0.62), cx + r, cy + int(r * 0.62)],
                   fill=int(95 * (1 - r / maxr)))
    glow = glow.filter(ImageFilter.GaussianBlur(int(70 * scale)))
    bg = Image.composite(Image.new("RGB", (W, H), glow_rgb), bg, glow)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * 0.22, -H * 0.22, W * 1.22, H * 1.22], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(int(220 * scale)))
    bg = Image.composite(bg, Image.new("RGB", (W, H), (0, 0, 0)), vig)
    scan = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scan)
    for y in range(0, H, 3):
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, 38), width=1)
    bg = Image.alpha_composite(bg.convert("RGBA"), scan).convert("RGB")
    bg.save(tmp / "bg.png")

    # foreground layer (transparent) — optional logo, title, subtitle, CTA pill
    title = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    has_logo = bool(logo and os.path.exists(logo))
    if has_logo:
        try:
            d = int(232 * scale)
            av = Image.open(logo).convert("RGBA").resize((d, d), Image.LANCZOS)
            mask = Image.new("L", (d, d), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
            lx, ly = (W - d) // 2, int(H * 0.12)
            ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse([lx - 7, ly - 7, lx + d + 7, ly + d + 7],
                                         outline=(*glow_rgb, 255), width=max(2, int(5 * scale)))
            title = Image.alpha_composite(title, ring)
            title.paste(av, (lx, ly), mask)
        except Exception:
            has_logo = False

    tsize = int((132 if has_logo else 158) * scale)
    tfont = find_font(tsize, bold=True)
    tr = int(18 * scale)
    d0 = ImageDraw.Draw(title)
    tw = _tracked_width(d0, text, tfont, tr)
    tx = int((W - tw) / 2)
    ty = int(H * (0.46 if has_logo else 0.38))
    glay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _draw_tracked(ImageDraw.Draw(glay), (tx, ty), text, tfont, (*glow_rgb, 255), tr)
    title = Image.alpha_composite(title, glay.filter(ImageFilter.GaussianBlur(int(20 * scale))))
    td = ImageDraw.Draw(title)
    _draw_tracked(td, (tx, ty), text, tfont, (238, 238, 240, 255), tr)

    y_cursor = ty + tsize + int(44 * scale)
    if sub:
        sfont = find_font(int(40 * scale), bold=False)
        st = int(14 * scale)
        sw = _tracked_width(td, sub, sfont, st)
        sx = int((W - sw) / 2)
        lw = int(300 * scale)
        td.line([((W - lw) // 2, y_cursor - int(16 * scale)),
                 ((W + lw) // 2, y_cursor - int(16 * scale))],
                fill=(*[min(255, c + 30) for c in glow_rgb], 210), width=max(1, int(2 * scale)))
        _draw_tracked(td, (sx, y_cursor), sub, sfont, (168, 168, 172, 255), st)
        y_cursor += int(78 * scale)

    if cta:
        cfont = find_font(int(46 * scale), bold=True)
        ct = int(10 * scale)
        ctext = cta.upper()
        cw = _tracked_width(td, ctext, cfont, ct)
        bx, by = int((W - cw) / 2), y_cursor + int(8 * scale)
        pad_x, pad_y = int(34 * scale), int(16 * scale)
        ImageDraw.Draw(title).rounded_rectangle(
            [bx - pad_x, by - pad_y, bx + cw + pad_x, by + int(46 * scale) + pad_y],
            radius=int(26 * scale), fill=(*glow_rgb, 235))
        _draw_tracked(td, (bx, by), ctext, cfont, (255, 255, 255, 255), ct)

    title.save(tmp / "title.png")


def make_title_card(out: str, text: str, sub: str = "", seconds: float = 6.0,
                    style: str = "horror", size=(1920, 1080), fps: int = 60,
                    letterbox: float = 0.07, flicker: bool | None = None,
                    audio: bool = True, crf: int = 20, preset: str = "medium",
                    logo: str | None = None, cta: str | None = None) -> str:
    """Render an animated title / intro / outro card to an mp4."""
    _glow, style_flicker, grain = _STYLES.get(style, _STYLES["horror"])
    if flicker is None:
        flicker = style_flicker
    tmp = Path(tempfile.mkdtemp(prefix="ff_title_"))
    _make_assets(text, sub, size, style, tmp, logo=logo, cta=cta)

    if flicker:
        appear = ("enable='between(t,1.15,1.22)+between(t,1.32,1.40)"
                  f"+gte(t,1.52)'")
    else:
        appear = "enable='gte(t,0.4)'"

    fout = max(0.4, seconds - 0.6)
    chain = [
        f"[0:v]format=yuv420p,noise=alls={grain}:allf=t+u,vignette=PI/6[bg]",
        f"[bg][1:v]overlay=(W-w)/2:(H-h)/2:{appear}[cv]",
    ]
    post = []
    if letterbox and letterbox > 0:
        post.append(f"drawbox=y=0:w=iw:h=ih*{letterbox}:color=black:t=fill")
        post.append(f"drawbox=y=ih*(1-{letterbox}):w=iw:h=ih*{letterbox}:color=black:t=fill")
    post.append(f"fade=t=in:st=0:d=0.5")
    post.append(f"fade=t=out:st={fout:.2f}:d=0.6")
    post.append("format=yuv420p")
    chain.append("[cv]" + ",".join(post) + "[v]")

    args = ["-loop", "1", "-t", str(seconds), "-i", str(tmp / "bg.png"),
            "-loop", "1", "-t", str(seconds), "-i", str(tmp / "title.png")]
    maps = ["-map", "[v]"]
    if audio:
        args += ["-f", "lavfi", "-t", str(seconds), "-i",
                 "anoisesrc=color=brown:amplitude=0.4:seed=7"]
        af = (f"[2:a]lowpass=f=180,volume=0.33,afade=t=in:st=0:d=1.2,"
              f"afade=t=out:st={max(0.1, seconds-1.2):.2f}:d=1.2[a]")
        chain.append(af)
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
    fc = ";".join(chain)
    args += ["-filter_complex", fc, *maps, "-r", str(fps),
             "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
             str(out)]
    ffmpeg(args)
    return out
