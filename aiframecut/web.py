"""Fetch PUBLIC YouTube channel branding (avatar + name) — no API key, no login.

Reads a channel's public page and pulls the Open Graph avatar image + title. This is
the only part of AI Frame Cut that touches the network (besides the one-time Whisper
model download). It only ever reads public metadata — never anything that needs a login.
"""
from __future__ import annotations

import io
import re
import urllib.request
from pathlib import Path

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _normalize(url_or_handle: str) -> str:
    s = url_or_handle.strip()
    if s.startswith("http"):
        return s
    if s.startswith("@"):
        return f"https://www.youtube.com/{s}"
    if s.startswith(("channel/", "c/", "user/", "@")):
        return f"https://www.youtube.com/{s}"
    return f"https://www.youtube.com/@{s}"


def _get(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "ignore")


def _meta(html: str, prop: str):
    for pat in (rf'<meta[^>]+property="{prop}"[^>]+content="([^"]+)"',
                rf'<meta[^>]+content="([^"]+)"[^>]+property="{prop}"',
                rf'<meta[^>]+name="{prop}"[^>]+content="([^"]+)"'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def fetch_channel(url_or_handle: str, outdir) -> dict:
    """Return {name, avatar_url, avatar_file, channel_url}. Downloads the avatar as PNG."""
    url = _normalize(url_or_handle)
    html = _get(url)
    name = _meta(html, "og:title")
    avatar = _meta(html, "og:image")
    m = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
    canonical = m.group(1) if m else url

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    saved = None
    if avatar:
        try:
            from PIL import Image
            raw = _get(avatar, binary=True)
            saved = str(outdir / "channel_avatar.png")
            Image.open(io.BytesIO(raw)).convert("RGBA").save(saved)
        except Exception:
            saved = None
    return {"name": name, "avatar_url": avatar, "avatar_file": saved, "channel_url": canonical}
