"""Declarative hand-drawn animation engine.

Describe a scene (or a list of scenes) in JSON — shapes, paths, text, sprites, a silhouette
character, effects — with any numeric property keyframed as {"k": [[t, value], ...]}.
Renders "on twos" with line boil, double ink strokes, paper grain and a vignette, then
encodes to MP4. Everything is pure PIL + numpy; no models, no network.

Minimal scene:
{
  "size": [1920, 1080], "fps": 24, "duration": 4,
  "background": {"type": "gradient", "top": [28,24,66], "mid": [196,96,84], "bottom": [255,178,96]},
  "layers": [
    {"type": "ellipse", "center": {"k": [[0,[1040,700]],[4,[1040,600]]]}, "radius": 95,
     "fill": [255,241,205], "glow": [255,214,120]},
    {"type": "ridge", "seed": 21, "base": 700, "amp": 80, "fill": [88,52,92], "stroke": 4},
    {"type": "figure", "at": [1180, 905], "height": 380, "pose": "stand"},
    {"type": "text", "text": "DAWN", "at": [960, 300], "size": 120, "brush": true, "from": 1, "to": 3}
  ]
}
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from ._ffmpeg import FFMPEG, ffmpeg

INK = (26, 20, 24)
PAPER = (246, 240, 228)

# ---------------------------------------------------------------- helpers
def _lerp(a, b, u):
    if isinstance(a, (list, tuple)):
        return [_lerp(x, y, u) for x, y in zip(a, b)]
    return a + (b - a) * u


def _ease(u, kind):
    if kind == "smooth":
        return u * u * (3 - 2 * u)
    if kind == "in":
        return u * u
    if kind == "out":
        return 1 - (1 - u) ** 2
    return u


def val(v, t):
    """Resolve a static or keyframed property at time t."""
    if isinstance(v, dict) and "k" in v:
        keys = sorted(v["k"], key=lambda p: p[0])
        ease = v.get("ease", "linear")
        if t <= keys[0][0]:
            return keys[0][1]
        for (t0, a), (t1, b) in zip(keys, keys[1:]):
            if t0 <= t <= t1:
                u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                return _lerp(a, b, _ease(u, ease))
        return keys[-1][1]
    return v


def rgb(c):
    return tuple(int(round(x)) for x in c[:3])


def rgba(c, a=255):
    c = list(c)
    return (int(c[0]), int(c[1]), int(c[2]), int(c[3] if len(c) > 3 else a))


_FONT_CACHE = {}
def font(kind, size):
    key = (kind, int(size))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    fdir = r"C:\Windows\Fonts" if os.name == "nt" else "/usr/share/fonts/truetype"
    table = {
        "jp": ["YuGothB.ttc", "msgothic.ttc", "meiryob.ttc"],
        "sans": ["bahnschrift.ttf", "arialbd.ttf", "dejavu/DejaVuSans-Bold.ttf"],
        "serif": ["georgiab.ttf", "timesbd.ttf", "dejavu/DejaVuSerif-Bold.ttf"],
        "impact": ["impact.ttf", "arialbd.ttf"],
    }
    cands = table.get(kind, [kind])  # a literal path also works
    f = None
    for c in cands:
        p = c if os.path.isabs(c) else os.path.join(fdir, c)
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, int(size)); break
            except Exception:
                pass
    f = f or ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


# ------------------------------------------------------------- ink tools
def wob(pts, amp, rng):
    if amp <= 0:
        return [tuple(p) for p in pts]
    return [(x + rng.uniform(-amp, amp), y + rng.uniform(-amp, amp)) for x, y in pts]


def ink_stroke(d, pts, rng, amp, w, color, closed=False):
    if len(pts) < 2 or w <= 0:
        return
    p = wob(pts, amp, rng)
    if closed:
        p = p + [p[0]]
    d.line(p, fill=color, width=int(w), joint="curve")
    if w >= 3:
        q = wob(pts, amp * 0.8, rng)
        if closed:
            q = q + [q[0]]
        d.line(q, fill=color, width=max(1, int(w) - 2), joint="curve")


def ribbon(d, path, widths, fill, rng, amp):
    left, right = [], []
    for i, (x, y) in enumerate(path):
        if i < len(path) - 1:
            dx, dy = path[i + 1][0] - x, path[i + 1][1] - y
        else:
            dx, dy = x - path[i - 1][0], y - path[i - 1][1]
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        left.append((x + nx * widths[i], y + ny * widths[i]))
        right.append((x - nx * widths[i], y - ny * widths[i]))
    d.polygon(wob(left + right[::-1], amp, rng), fill=fill)


# ----------------------------------------------------------- generators
def ridge_pts(seed, base, amp, W, xoff=0.0, step=22):
    r = random.Random(seed); ph = [r.uniform(0, 6.28) for _ in range(3)]
    return [(x, base + amp * (0.55 * math.sin((x + xoff) / W * 3.1 + ph[0])
                              + 0.30 * math.sin((x + xoff) / W * 7.3 + ph[1])
                              + 0.15 * math.sin((x + xoff) / W * 15.7 + ph[2])))
            for x in range(-120, W + 220, step)]


def ridge_y(pts, x):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * ((x - x0) / (x1 - x0))
    return pts[-1][1]


def paper_texture(W, H, seed=7):
    rng = np.random.default_rng(seed)
    base = np.full((H, W, 3), PAPER, dtype=np.float32) + rng.normal(0, 6, (H, W, 1))
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img); r = random.Random(seed)
    for _ in range(int(W * H / 800)):
        x, y = r.uniform(0, W), r.uniform(0, H); L = r.uniform(6, 40); a = r.uniform(0, math.pi)
        d.line([(x, y), (x + L * math.cos(a), y + L * math.sin(a))], fill=(224, 214, 197), width=1)
    return img.filter(ImageFilter.GaussianBlur(0.6))


def vignette_mask(W, H, strength=105):
    v = Image.new("L", (W, H), 0)
    ImageDraw.Draw(v).ellipse([-W * 0.25, -H * 0.3, W * 1.25, H * 1.3], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(int(W * 0.14)))
    return ImageChops.add(v, Image.new("L", (W, H), 255 - strength))


# --------------------------------------------------------------- engine
class Renderer:
    def __init__(self, scene: dict, base_dir: Path):
        self.sc = scene
        self.base = base_dir
        self.W, self.H = scene.get("size", [1920, 1080])
        self.fps = int(scene.get("fps", 24))
        self.on_twos = bool(scene.get("on_twos", True))
        st = scene.get("style", {})
        self.boil = float(st.get("boil", 1.6))
        self.ink = rgb(st.get("ink", INK))
        self.paper_on = bool(st.get("paper", True))
        self.paper_mix = float(st.get("paper_strength", 0.55))
        self.vig_on = bool(st.get("vignette", True))
        self.paper = paper_texture(self.W, self.H)
        self.paper_rgba = self.paper.convert("RGBA")
        self.vig = vignette_mask(self.W, self.H, int(st.get("vignette_strength", 105)))
        self.black = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        self._sprites = {}

    # ---- background
    def background(self, t, nrng):
        bg = self.sc.get("background", {"type": "paper"})
        kind = bg.get("type", "paper")
        W, H = self.W, self.H
        if kind == "paper":
            return self.paper_rgba.copy()
        if kind == "solid":
            return Image.new("RGBA", (W, H), rgba(val(bg.get("color", PAPER), t)))
        # gradient (top / mid / bottom, all keyframable)
        top = np.array(val(bg.get("top", [28, 24, 66]), t), np.float32)
        mid = np.array(val(bg.get("mid", top), t), np.float32)
        bot = np.array(val(bg.get("bottom", mid), t), np.float32)
        split = float(bg.get("split", 0.58))
        ys = np.linspace(0, 1, H)[:, None]
        col = np.where(ys < split, top + (mid - top) * (ys / split), mid + (bot - mid) * ((ys - split) / (1 - split)))
        arr = np.repeat(col[:, None, :], W, axis=1) + nrng.normal(0, float(bg.get("grain", 4.5)), (H, W, 1))
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")

    # ---- layers
    def sprite(self, src):
        p = str(self.base / src) if not os.path.isabs(src) else src
        if p not in self._sprites:
            self._sprites[p] = Image.open(p).convert("RGBA")
        return self._sprites[p]

    def _glow(self, color, radius, strength):
        key = ("glow", color, radius, strength)
        if key not in self._sprites:
            n = max(4, radius * 2); yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
            rr = np.sqrt((xx - n / 2) ** 2 + (yy - n / 2) ** 2) / (n / 2)
            a = np.clip(1 - rr, 0, 1) ** 2.2 * 255 * min(1.0, 0.22 * strength)
            im = np.zeros((n, n, 4), np.uint8); im[..., :3] = color; im[..., 3] = a.astype(np.uint8)
            if len(self._sprites) > 80:
                self._sprites = {k: v for k, v in self._sprites.items() if not (isinstance(k, tuple) and k[0] == "glow")}
            self._sprites[key] = Image.fromarray(im, "RGBA")
        return self._sprites[key]

    def _scaled(self, src, size):
        key = (src, size)
        if key not in self._sprites:
            if len(self._sprites) > 24:
                self._sprites = {k: v for k, v in self._sprites.items() if not isinstance(k, tuple)}
            self._sprites[key] = self.sprite(src).resize(size, Image.LANCZOS)
        return self._sprites[key]

    def _parallax(self, src, depth_src, size, px, py):
        """Shift each pixel by (px, py) * depth (near = 1). Cheap 2.5D camera move on a painting."""
        from scipy.ndimage import map_coordinates
        dkey = ("depth", depth_src, size)
        if dkey not in self._sprites:
            dp = str(self.base / depth_src) if not os.path.isabs(depth_src) else depth_src
            dm = Image.open(dp).convert("L").resize(size, Image.BILINEAR)
            self._sprites[dkey] = np.asarray(dm, np.float32) / 255.0
        depth = self._sprites[dkey]
        gkey = ("grid", size)
        if gkey not in self._sprites:
            h, w = depth.shape
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            self._sprites[gkey] = (xx, yy)
        xx, yy = self._sprites[gkey]
        sx = xx - px * depth; sy = yy - py * depth            # sample from where the pixel came from
        arr = np.asarray(self._scaled(src, size))
        try:
            import cv2
            out = cv2.remap(arr, sx, sy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        except ImportError:                                   # slow fallback
            arr = arr.astype(np.float32); out = np.empty_like(arr)
            for c in range(4):
                out[..., c] = map_coordinates(arr[..., c], [sy, sx], order=1, mode="nearest")
            out = np.clip(out, 0, 255).astype(np.uint8)
        return Image.fromarray(np.ascontiguousarray(out), "RGBA")

    def draw_layer(self, img, L, t, rng):
        W, H = self.W, self.H
        if t < float(L.get("from", -1e9)) or t > float(L.get("to", 1e9)):
            return img
        kind = L["type"]
        boil = float(val(L.get("boil", self.boil), t))
        ink = rgb(val(L.get("stroke_color", self.ink), t))
        stroke = float(val(L.get("stroke", 0), t))
        d = ImageDraw.Draw(img)

        if kind == "ellipse":
            cx, cy = val(L["center"], t); r = float(val(L["radius"], t))
            ry = float(val(L.get("radius_y", r), t))
            if L.get("glow"):                                  # smooth radial glow (cached per look)
                gc = rgb(val(L["glow"], t)); gs = float(val(L.get("glow_strength", 1.0), t)); gsp = float(L.get("glow_spread", 0.38))
                g = self._glow(gc, int(r * (1 + 7 * gsp)), round(gs, 2))
                img.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2))); d = ImageDraw.Draw(img)
            cut = L.get("cut")                                  # erase a circle from the disc (a bitten sun)
            if L.get("fill") is not None and cut:
                lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
                ld.ellipse([cx - r, cy - ry, cx + r, cy + ry], fill=rgba(val(L["fill"], t)))
                ccx, ccy = val(cut["center"], t); cr = float(val(cut.get("radius", r), t))
                ld.ellipse([ccx - cr, ccy - cr, ccx + cr, ccy + cr], fill=(0, 0, 0, 0))
                img.alpha_composite(lay); d = ImageDraw.Draw(img)
            elif L.get("fill") is not None:
                d.ellipse([cx - r, cy - ry, cx + r, cy + ry], fill=rgba(val(L["fill"], t)))
            if stroke > 0:
                n = 40
                pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]
                ink_stroke(d, pts, rng, boil, stroke, ink, closed=True)

        elif kind == "rect":
            x, y = val(L["at"], t); w, h = val(L["size"], t)
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            if L.get("fill") is not None:
                d.polygon(wob(pts, boil, rng), fill=rgba(val(L["fill"], t)))
            if stroke > 0:
                ink_stroke(d, pts, rng, boil, stroke, ink, closed=True)

        elif kind == "polygon":
            pts = [tuple(p) for p in val(L["points"], t)]
            if L.get("fill") is not None:
                d.polygon(wob(pts, boil, rng), fill=rgba(val(L["fill"], t)))
            if stroke > 0:
                ink_stroke(d, pts, rng, boil, stroke, ink, closed=True)

        elif kind == "path":
            pts = [tuple(p) for p in val(L["points"], t)]
            ink_stroke(d, pts, rng, boil, stroke or 3, rgb(val(L.get("color", ink), t)))

        elif kind == "ridge":
            cam = float(val(L.get("scroll", 0), t))
            pts = ridge_pts(int(L.get("seed", 1)), float(val(L["base"], t)), float(val(L.get("amp", 60), t)), W, xoff=cam)
            d.polygon(pts + [(W + 220, H + 60), (-120, H + 60)], fill=rgba(val(L.get("fill", [60, 40, 70]), t)))
            if stroke > 0:
                ink_stroke(d, pts, rng, boil * 1.4, stroke, ink)
            if L.get("grass"):
                g = L["grass"]; gr = random.Random(int(g.get("seed", 4)))
                gc = rgb(g.get("color", ink)); step = int(g.get("step", 16))
                for x in range(-40, W + 40, step):
                    gy = ridge_y(pts, x); h = gr.uniform(*g.get("height", [30, 95])); lean = gr.uniform(-25, 25) + 14
                    ink_stroke(d, [(x, gy + 6), (x + lean * 0.5, gy - h * 0.55), (x + lean, gy - h)], rng, 1.4, 3, gc)

        elif kind == "text":
            op = float(val(L.get("opacity", 1.0), t))
            if op <= 0:
                return img
            layer = img if op >= 0.999 else Image.new("RGBA", (W, H), (0, 0, 0, 0))
            td = ImageDraw.Draw(layer)
            x, y = val(L["at"], t); size = int(val(L.get("size", 80), t))
            f = font(L.get("font", "sans"), size); color = rgb(val(L.get("color", ink), t))
            text = L["text"]
            if L.get("brush", False):
                jit = float(L.get("jitter", 2.0))
                for _ in range(3):
                    td.text((x + rng.uniform(-jit, jit), y + rng.uniform(-jit, jit)), text, font=f, fill=color, anchor="mm")
                x0, y0, x1, y1 = td.textbbox((x, y), text, font=f, anchor="mm")
                for _ in range(int(L.get("flecks", 14))):
                    fx = rng.uniform(x0 - 40, x1 + 40); fy = rng.uniform(y0 - 20, y1 + 20); r = rng.uniform(1, 4.5)
                    td.ellipse([fx - r, fy - r, fx + r, fy + r], fill=color)
            else:
                sw = int(L.get("outline", 0))
                td.text((x, y), text, font=f, fill=color, anchor=L.get("anchor", "mm"),
                        stroke_width=sw, stroke_fill=rgb(L.get("outline_color", ink)))
            if layer is not img:
                layer.putalpha(layer.getchannel("A").point(lambda v, o=op: int(v * o)))
                img.alpha_composite(layer)

        elif kind == "sprite":
            op = float(val(L.get("opacity", 1.0), t))
            if op <= 0:
                return img
            im = self.sprite(L["src"])
            sc = float(val(L.get("scale", 1.0), t)); rot = float(val(L.get("rotate", 0), t))
            if L.get("fit") == "cover":                      # scale to fill the frame (plus `scale` on top)
                sc *= max(W / im.width, H / im.height)
            x, y = val(L.get("at", [W / 2, H / 2]), t)
            size = (max(1, int(im.width * sc)), max(1, int(im.height * sc)))
            sp = self._scaled(L["src"], size)
            if L.get("depth"):                               # 2.5D parallax: shift pixels by depth
                px, py = val(L.get("parallax", [0, 0]), t)
                if abs(px) > 0.01 or abs(py) > 0.01:
                    sp = self._parallax(L["src"], L["depth"], size, float(px), float(py))
            br = float(val(L.get("brightness", 1.0), t)); tint = L.get("tint")
            if abs(br - 1.0) > 0.002 or tint is not None:
                arr = np.asarray(sp).astype(np.float32)
                m = (np.array(val(tint, t), np.float32) / 255.0) if tint is not None else np.ones(3, np.float32)
                arr[..., :3] = np.clip(arr[..., :3] * br * m, 0, 255)
                sp = Image.fromarray(arr.astype(np.uint8), "RGBA")
            if rot:
                sp = sp.rotate(-rot, resample=Image.BICUBIC, expand=True)
            if op < 1:
                sp = sp.copy(); sp.putalpha(sp.getchannel("A").point(lambda v, o=op: int(v * o)))
            img.alpha_composite(sp, (int(x - sp.width / 2), int(y - sp.height / 2)))

        elif kind == "stars":  # twinkling points; opacity keyframable so they can fade in at dusk
            op = float(val(L.get("opacity", 1.0), t))
            if op > 0:
                r = random.Random(int(L.get("seed", 3))); col = rgb(L.get("color", [255, 250, 235]))
                y0, y1 = L.get("band", [0, H * 0.6]); layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
                for _i in range(int(L.get("count", 160))):
                    x, y, sz, ph = r.uniform(0, W), r.uniform(y0, y1), r.uniform(0.8, 2.6), r.uniform(0, 6.28)
                    a_ = int(255 * op * (0.55 + 0.45 * math.sin(t * 2.1 + ph)))
                    ld.ellipse([x - sz, y - sz, x + sz, y + sz], fill=col + (max(0, a_),))
                img.alpha_composite(layer)

        elif kind == "lights":  # scattered warm lights in a region; "on" = fraction lit (keyframable)
            on = float(val(L.get("on", 1.0), t))
            if on > 0:
                r = random.Random(int(L.get("seed", 8))); col = rgb(L.get("color", [255, 200, 120]))
                x0, y0, x1, y1 = L.get("region", [0, H * 0.6, W, H]); layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
                for i in range(int(L.get("count", 120))):
                    x, y, sz, th = r.uniform(x0, x1), r.uniform(y0, y1), r.uniform(1.5, 4.0), r.random()
                    if th > on:
                        continue
                    a_ = int(230 * (0.75 + 0.25 * math.sin(t * 3 + i)))
                    ld.ellipse([x - sz * 3, y - sz * 3, x + sz * 3, y + sz * 3], fill=col + (int(a_ * 0.18),))
                    ld.ellipse([x - sz, y - sz, x + sz, y + sz], fill=col + (a_,))
                img.alpha_composite(layer)

        elif kind == "rays":  # soft light rays from a point (godrays); opacity keyframable
            op = float(val(L.get("opacity", 0.5), t))
            if op > 0:
                cx, cy = val(L.get("center", [W / 2, H * 0.3]), t); col = rgb(L.get("color", [255, 230, 180]))
                q = 4; cx, cy = cx / q, cy / q                  # drawn at quarter res, blurred, upscaled (cheap)
                r = random.Random(int(L.get("seed", 5))); layer = Image.new("RGBA", (W // q, H // q), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
                for i in range(int(L.get("count", 14))):
                    a0 = r.uniform(0, 6.283) + 0.05 * math.sin(t * 0.7 + i); wdt = r.uniform(0.02, 0.07)
                    ln = max(W, H) * 1.6 / q
                    pts = [(cx, cy), (cx + ln * math.cos(a0 - wdt), cy + ln * math.sin(a0 - wdt)), (cx + ln * math.cos(a0 + wdt), cy + ln * math.sin(a0 + wdt))]
                    ld.polygon(pts, fill=col + (int(255 * op * r.uniform(0.05, 0.14)),))
                layer = layer.filter(ImageFilter.GaussianBlur(max(1, int(L.get("blur", 40)) // q))).resize((W, H), Image.BILINEAR)
                img.alpha_composite(layer)

        elif kind == "figure":
            self.figure(d, L, t, rng)

        elif kind == "petals":
            self.petals(img, L, t, rng)

        elif kind == "clouds":
            self.clouds(img, L, t)

        elif kind == "birds":
            self.birds(d, L, t, rng)

        elif kind == "speedlines":
            cx, cy = val(L.get("center", [W / 2, H / 2]), t)
            col = rgb(val(L.get("color", ink), t))
            for _ in range(int(val(L.get("count", 90), t))):
                a = rng.uniform(0, 6.283); l1 = rng.uniform(200, 520); l2 = rng.uniform(950, 1500)
                d.line([(cx + l1 * math.cos(a), cy + l1 * math.sin(a)), (cx + l2 * math.cos(a), cy + l2 * math.sin(a))],
                       fill=col, width=rng.randint(2, int(L.get("max_width", 7))))

        elif kind == "flash":  # full-frame colour wash with opacity (impact frames, fades)
            op = float(val(L.get("opacity", 1.0), t))
            if op > 0:
                wash = Image.new("RGBA", (W, H), rgba(val(L.get("color", PAPER), t), int(255 * min(1, op))))
                img.alpha_composite(wash)
        return img

    # ---- character
    def figure(self, d, L, t, rng):
        cx, cy = val(L["at"], t); s = float(val(L.get("height", 380), t))
        pose = L.get("pose", "stand"); facing = int(L.get("facing", 1))
        lean = float(val(L.get("lean", 0), t)); wind = min(float(val(L.get("wind", 1.0), t)), 1.8)
        phase = float(val(L.get("phase", 0), t)) if "phase" in L else t * float(L.get("walk_speed", 7.0))
        ink = rgb(val(L.get("color", self.ink), t)); scarf = rgb(val(L.get("scarf", [176, 32, 44]), t))
        amp = 1.2

        oy = 0.40 if pose == "sit" else 0.0                 # sitting: `at` is the seat point

        def P(x, y):
            x *= facing; y += oy
            if lean:
                c, sn = math.cos(lean), math.sin(lean); x, y = x * c - y * sn, x * sn + y * c
            return (cx + x * s, cy + y * s)

        if pose == "sit":                                     # legs dangling over an edge
            ink_stroke(d, [P(0.03, -0.42), P(0.20, -0.36), P(0.22, -0.10)], rng, amp, 0.085 * s, ink)
            ink_stroke(d, [P(-0.03, -0.42), P(0.17, -0.33), P(0.19, -0.06)], rng, amp, 0.085 * s, ink)
        elif pose == "walk":
            for sign in (1, -1):
                sw = sign * math.sin(phase)
                ink_stroke(d, [P(0.03 * sign, -0.42), P(0.12 * sw + 0.02, -0.22 - 0.05 * max(0.0, sw)), P(0.21 * sw, -0.055 * max(0.0, sw))], rng, amp, 0.085 * s, ink)
        else:
            ink_stroke(d, [P(-0.05, -0.42), P(-0.075, -0.2), P(-0.08, 0.0)], rng, amp, 0.085 * s, ink)
            ink_stroke(d, [P(0.05, -0.42), P(0.07, -0.2), P(0.075, 0.0)], rng, amp, 0.085 * s, ink)
        d.polygon(wob([P(-0.12, -0.76), P(0.12, -0.76), P(0.14, -0.40), P(-0.14, -0.40)], amp, rng), fill=ink)
        if pose == "walk":
            for sign in (1, -1):
                sw = -sign * math.sin(phase)
                ink_stroke(d, [P(0.11 * sign, -0.73), P(0.13 * sign + 0.08 * sw, -0.58), P(0.12 * sign + 0.19 * sw, -0.45)], rng, amp, 0.065 * s, ink)
        elif pose == "turn":
            ink_stroke(d, [P(-0.11, -0.73), P(-0.30, -0.66), P(-0.42, -0.52)], rng, amp, 0.065 * s, ink)
            ink_stroke(d, [P(0.11, -0.73), P(0.28, -0.80), P(0.40, -0.92)], rng, amp, 0.065 * s, ink)
        elif pose == "point":
            ink_stroke(d, [P(-0.11, -0.73), P(-0.15, -0.58), P(-0.16, -0.43)], rng, amp, 0.065 * s, ink)
            ink_stroke(d, [P(0.11, -0.73), P(0.30, -0.74), P(0.48, -0.76)], rng, amp, 0.065 * s, ink)
        elif pose == "hold":                                  # one arm out, holding something
            ink_stroke(d, [P(-0.11, -0.73), P(-0.15, -0.58), P(-0.16, -0.43)], rng, amp, 0.065 * s, ink)
            ink_stroke(d, [P(0.11, -0.73), P(0.24, -0.62), P(0.30, -0.50)], rng, amp, 0.065 * s, ink)
        elif pose == "sit":
            ink_stroke(d, [P(-0.11, -0.73), P(-0.17, -0.58), P(-0.19, -0.44)], rng, amp, 0.065 * s, ink)
            ink_stroke(d, [P(0.11, -0.73), P(0.20, -0.58), P(0.22, -0.42)], rng, amp, 0.065 * s, ink)
        else:
            ink_stroke(d, [P(-0.11, -0.73), P(-0.15, -0.58), P(-0.16, -0.43)], rng, amp, 0.065 * s, ink)
            ink_stroke(d, [P(0.11, -0.73), P(0.16, -0.58), P(0.17, -0.44)], rng, amp, 0.065 * s, ink)
        lan = L.get("lantern")
        if lan:                                               # a glowing lantern hanging from the hand
            hand = {"hold": P(0.30, -0.50), "sit": P(0.22, -0.42), "point": P(0.48, -0.76)}.get(pose, P(0.17, -0.44))
            lit = float(val(lan.get("lit", 1.0), t)); lr = 0.045 * s * float(lan.get("size", 1.0))
            lx, ly = hand[0], hand[1] + 0.07 * s
            ink_stroke(d, [hand, (lx, ly - lr)], rng, 0.6, max(1, 0.01 * s), ink)
            if lit > 0:
                gc = rgb(lan.get("glow", [255, 170, 70])); gs = float(lan.get("strength", 2.0)) * lit
                for k in range(6, 0, -1):
                    rr = lr * (1 + k * 0.7)
                    d.ellipse([lx - rr, ly - rr, lx + rr, ly + rr], fill=gc + (max(2, min(255, int((26 - k * 3) * gs))),))
            body = rgb(lan.get("color", [255, 214, 140])) if lit > 0 else ink
            d.ellipse([lx - lr, ly - lr * 1.25, lx + lr, ly + lr * 1.25], fill=body)
            ink_stroke(d, [(lx - lr, ly - lr * 1.25), (lx + lr, ly - lr * 1.25)], rng, 0.6, max(1, 0.012 * s), ink)
        ink_stroke(d, [P(0, -0.78), P(0, -0.82)], rng, 0.8, 0.06 * s, ink)
        hx, hy = P(0, -0.885); hr = 0.078 * s
        d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=ink)
        d.polygon(wob([P(-0.09, -0.90), P(-0.06, -0.975), P(0.02, -0.99), P(0.09, -0.96), P(0.10, -0.90), P(0.06, -0.87), P(-0.07, -0.86)], 1.0, rng), fill=ink)
        d.polygon(wob([P(0.03, -0.93), P(0.11, -0.92), P(0.13, -0.85), P(0.08, -0.86)], 1.0, rng), fill=ink)
        if L.get("hair", True):
            for (sy, ln, bw, ph) in [(-0.95, 0.36, 0.056, 0.0), (-0.92, 0.44, 0.050, 0.9), (-0.89, 0.32, 0.042, 1.7), (-0.86, 0.24, 0.034, 2.6), (-0.83, 0.16, 0.026, 3.4)]:
                path, widths = [], []
                for i in range(7):
                    u = i / 6; wave = math.sin(t * 5.2 + ph + u * 4.0) * (0.02 + 0.11 * u) * wind
                    path.append(P(-0.02 - ln * u, sy + 0.05 * u + wave)); widths.append(bw * (1 - u * 0.85) * s)
                ribbon(d, path, widths, ink, rng, 1.1)
        if L.get("scarf", True) is not False:
            path, widths = [], []
            for i in range(8):
                u = i / 7; wave = math.sin(t * 4.4 + u * 5.0 + 0.5) * (0.02 + 0.12 * u) * wind
                path.append(P(-0.05 - 0.58 * u, -0.76 + 0.09 * u + wave)); widths.append(0.042 * (1 - u * 0.5) * s)
            ribbon(d, path, widths, scarf, rng, 1.3)
            ink_stroke(d, path, rng, 1.0, max(1, 0.012 * s), ink)

    # ---- effects
    def petals(self, img, L, t, rng):
        W, H = self.W, self.H
        r = random.Random(int(L.get("seed", 5))); n = int(L.get("count", 40))
        col = rgba(L.get("color", [255, 186, 200]), 238); shade = rgba(L.get("shade", [232, 118, 150]), 80)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        for _ in range(n):
            x0, y0, sc, rot0, fall, ph = r.uniform(-200, W + 200), r.uniform(-H, H), r.uniform(0.6, 1.35), r.uniform(0, 6.28), r.uniform(28, 62), r.uniform(0, 6.28)
            y = (y0 + fall * t * float(L.get("speed", 1))) % (H + 200) - 100
            x = (x0 + 44 * math.sin(t * 0.9 + ph) + 26 * t) % (W + 300) - 150
            rot = rot0 + t * 2.4; s = 12 * sc * float(L.get("scale", 1)); c, sn = math.cos(rot), math.sin(rot)
            pts = [(x + s * c, y + s * 0.55 * sn), (x - s * 0.55 * sn, y + s * 0.55 * c), (x - s * c, y - s * 0.55 * sn), (x + s * 0.55 * sn, y - s * 0.55 * c)]
            d.polygon(wob(pts, 0.8, rng), fill=col); d.polygon([(px + 1.5, py + 2.5) for px, py in pts], fill=shade)
        img.alpha_composite(layer)

    def clouds(self, img, L, t):
        W, H = self.W, self.H
        r = random.Random(int(L.get("seed", 11))); col = rgb(L.get("color", [255, 236, 214])); a = int(L.get("opacity", 110))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        for _ in range(int(L.get("count", 7))):
            bx, by, sc, sp = r.uniform(0, W), r.uniform(*L.get("band", [70, 420])), r.uniform(0.7, 1.4), r.uniform(9, 22)
            x = (bx + t * sp * float(L.get("speed", 1))) % (W + 500) - 250
            for _j in range(5):
                ox, oy = r.uniform(-95, 95) * sc, r.uniform(-18, 18) * sc; rw = r.uniform(60, 125) * sc; rh = rw * 0.42
                d.ellipse([x + ox - rw, by + oy - rh, x + ox + rw, by + oy + rh], fill=col + (a,))
        img.alpha_composite(layer)

    def birds(self, d, L, t, rng):
        r = random.Random(int(L.get("seed", 9))); bx, by = val(L.get("at", [1500, 250]), t)
        col = rgb(L.get("color", self.ink)); t0 = float(L.get("from", 0))
        for i in range(int(L.get("count", 6))):
            ox, oy, sp = r.uniform(-140, 140), r.uniform(-70, 70), r.uniform(20, 40)
            x = bx + ox - (t - t0) * sp * 2.2 * float(L.get("speed", 1)); y = by + oy + 12 * math.sin(t * 3 + i)
            flap = 8 * math.sin(t * 9 + i)
            ink_stroke(d, [(x - 18, y + flap), (x, y - 4), (x + 18, y + flap)], rng, 1.0, 3, col)

    # ---- frame
    def render(self, t, k):
        rng = random.Random(1000 + k); nrng = np.random.default_rng(500 + k)
        img = self.background(t, nrng)
        layers = self.sc.get("layers", [])
        for L in layers:
            if not L.get("screen"):                          # world layers (camera applies)
                img = self.draw_layer(img, L, t, rng)
        cam = self.sc.get("camera")
        if cam:
            z = float(val(cam.get("zoom", 1.0), t))
            if z > 1.0005:
                cx, cy = val(cam.get("center", [self.W / 2, self.H / 2]), t)
                cw, ch = self.W / z, self.H / z
                x0 = min(max(0.0, cx - cw / 2), self.W - cw); y0 = min(max(0.0, cy - ch / 2), self.H - ch)
                img = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((self.W, self.H), Image.BILINEAR)
        for L in layers:
            if L.get("screen"):                              # screen layers: subtitles, clocks, titles (no camera)
                img = self.draw_layer(img, L, t, rng)
        out = img.convert("RGB")
        if self.paper_on:
            out = Image.blend(out, ImageChops.multiply(out, self.paper), self.paper_mix)
        if self.vig_on:
            out = Image.composite(out, self.black, self.vig)
        return out


def load_scene(path) -> tuple[dict, Path]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")), p.parent


def render_video(scene_path, out, on_progress=None, gpu: bool = False) -> str:
    """Render a scene file (single scene or {"scenes":[...]}) to MP4, streaming frames to ffmpeg."""
    doc, base = load_scene(scene_path)
    scenes = doc["scenes"] if "scenes" in doc else [doc]
    shared = {k: v for k, v in doc.items() if k in ("size", "fps", "on_twos", "style")}
    fps = int(shared.get("fps", scenes[0].get("fps", 24)))
    W, H = shared.get("size", scenes[0].get("size", [1920, 1080]))
    args = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", str(fps), "-i", "-"]
    audio = doc.get("audio")
    if audio:
        ap = str(base / audio) if not os.path.isabs(audio) else audio
        args += ["-i", ap, "-shortest", "-c:a", "aac", "-b:a", "192k"]
    if gpu:
        args += ["-c:v", "h264_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "17", "-b:v", "0"]
    else:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
    args += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    enc = subprocess.Popen(args, stdin=subprocess.PIPE)
    try:
        for si, sc in enumerate(scenes):
            sc = {**shared, **sc}
            R = Renderer(sc, base)
            dur = float(sc.get("duration", 4.0)); step = 2 if R.on_twos else 1
            n = int(round(dur * R.fps)); fade = float(sc.get("fade_in", 0)); fout = float(sc.get("fade_out", 0))
            fade_img = R.black if sc.get("fade_to", "paper") == "black" else R.paper
            k = 0
            while k < n:
                t = k / R.fps
                im = R.render(t, k)
                if fade and t < fade:
                    im = Image.blend(fade_img, im, t / fade)
                if fout and t > dur - fout:
                    im = Image.blend(im, fade_img, min(1.0, (t - (dur - fout)) / fout))
                data = im.tobytes()
                for _ in range(min(step, n - k)):
                    enc.stdin.write(data)
                k += step
                if on_progress and k % 24 == 0:
                    on_progress(si, len(scenes), t, dur)
    finally:
        enc.stdin.close(); enc.wait()
    return str(out)


def render_frame(scene_path, t: float, out) -> str:
    doc, base = load_scene(scene_path)
    scenes = doc["scenes"] if "scenes" in doc else [doc]
    shared = {k: v for k, v in doc.items() if k in ("size", "fps", "on_twos", "style")}
    acc = 0.0
    for sc in scenes:
        sc = {**shared, **sc}; dur = float(sc.get("duration", 4.0))
        if t <= acc + dur or sc is scenes[-1]:
            R = Renderer(sc, base)
            R.render(t - acc, int((t - acc) * R.fps)).save(out)
            return str(out)
        acc += dur
    return str(out)
