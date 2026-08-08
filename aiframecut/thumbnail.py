"""PIL-based YouTube thumbnail maker: a frame + big bold outlined text + optional avatar."""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .titles import find_font


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if not cur or draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_thumbnail(out: str, frame_img: str, text: str, sub: str = "",
                   logo: str | None = None, accent=(230, 40, 60), size=(1280, 720)) -> str:
    W, H = size
    base = ImageOps.fit(Image.open(frame_img).convert("RGB"), (W, H), Image.LANCZOS).convert("RGBA")

    # bottom-heavy darkening so text pops
    grad = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        gd.line([(0, y), (W, y)], fill=int(215 * (y / H) ** 1.6))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    shade.putalpha(grad)
    base = Image.alpha_composite(base, shade)

    # gentle vignette
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * 0.2, -H * 0.2, W * 1.2, H * 1.2], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(160))
    base = Image.composite(base, Image.new("RGBA", (W, H), (0, 0, 0, 255)), vig)

    draw = ImageDraw.Draw(base)
    text = text.upper()
    margin = 60
    fsize = 138
    font = find_font(fsize, bold=True)
    lines = _wrap(draw, text, font, W - 2 * margin)
    while len(lines) > 3 and fsize > 66:
        fsize -= 12
        font = find_font(fsize, bold=True)
        lines = _wrap(draw, text, font, W - 2 * margin)

    lh = int(fsize * 1.12)
    total_h = lh * len(lines)
    y = H - margin - total_h - (58 if sub else 0)

    # accent bar above the headline
    draw.rectangle([margin, y - 26, margin + int(W * 0.17), y - 12], fill=accent + (255,))
    for i, ln in enumerate(lines):
        draw.text((margin, y + i * lh), ln, font=font, fill=(255, 255, 255),
                  stroke_width=max(4, fsize // 15), stroke_fill=(0, 0, 0))
    if sub:
        sfont = find_font(48, bold=True)
        draw.text((margin, y + total_h + 12), sub.upper(), font=sfont,
                  fill=accent + (255,), stroke_width=3, stroke_fill=(0, 0, 0))

    # circular avatar badge, top-right
    if logo and os.path.exists(logo):
        try:
            d = 196
            av = Image.open(logo).convert("RGBA").resize((d, d), Image.LANCZOS)
            mask = Image.new("L", (d, d), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
            lx, ly = W - d - margin, margin
            ImageDraw.Draw(base).ellipse([lx - 6, ly - 6, lx + d + 6, ly + d + 6],
                                         outline=(255, 255, 255, 255), width=6)
            base.paste(av, (lx, ly), mask)
        except Exception:
            pass

    base.convert("RGB").save(out)
    return out
