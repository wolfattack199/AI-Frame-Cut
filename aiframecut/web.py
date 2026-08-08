"""Fetch PUBLIC profile branding (avatar + name) from YouTube, Steam, Roblox, or any
og:image page — no API keys, no logins.

This is the only part of AI Frame Cut that touches the network (besides the one-time
Whisper model download). It only ever reads PUBLIC metadata — never anything private.
"""
from __future__ import annotations

import io
import json
import re
import urllib.request
from pathlib import Path

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _get(url: str, binary: bool = False, data: bytes | None = None, headers: dict | None = None):
    h = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
    return raw if binary else raw.decode("utf-8", "ignore")


def _get_json(url: str):
    return json.loads(_get(url, headers={"Accept": "application/json"}))


def _meta(html: str, prop: str):
    for pat in (rf'<meta[^>]+property="{prop}"[^>]+content="([^"]+)"',
                rf'<meta[^>]+content="([^"]+)"[^>]+property="{prop}"',
                rf'<meta[^>]+name="{prop}"[^>]+content="([^"]+)"'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _detect(s: str) -> str:
    low = s.lower()
    if "youtube.com" in low or "youtu.be" in low:
        return "youtube"
    if "steamcommunity.com" in low:
        return "steam"
    if "roblox.com" in low:
        return "roblox"
    if s.startswith("http"):
        return "generic"
    return "youtube"  # a bare handle defaults to YouTube


def _save_avatar(url: str, outdir, stem: str = "channel_avatar"):
    from PIL import Image
    raw = _get(url, binary=True)
    p = Path(outdir)
    p.mkdir(parents=True, exist_ok=True)
    out = str(p / f"{stem}.png")
    Image.open(io.BytesIO(raw)).convert("RGBA").save(out)
    return out


def _youtube(s: str):
    url = s if s.startswith("http") else f"https://www.youtube.com/{s if s.startswith('@') else '@' + s}"
    html = _get(url)
    m = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
    return _meta(html, "og:title"), _meta(html, "og:image"), (m.group(1) if m else url)


def _steam(s: str):
    url = s if s.startswith("http") else f"https://steamcommunity.com/id/{s}"
    html = _get(url)
    name = _meta(html, "og:title")
    if name and "::" in name:  # "Steam Community :: Name"
        name = name.split("::")[-1].strip()
    # the real avatar lives in the profile's avatar element, NOT og:image (which is generic)
    avatar = None
    m = re.search(r'playerAvatar[^>]*>\s*<img[^>]+src="([^"]+_full\.jpg)"', html)
    if not m:
        m = re.search(r'(https://[^"\']+steamstatic\.com/[0-9a-f]{20,}_full\.jpg)', html)
    if m:
        avatar = m.group(1)
    return name, avatar or _meta(html, "og:image"), url


def _roblox(s: str):
    uid = None
    m = re.search(r"/users/(\d+)", s)
    if m:
        uid = m.group(1)
    elif s.strip().isdigit():
        uid = s.strip()
    else:  # resolve a username -> id
        try:
            body = json.dumps({"usernames": [s.lstrip("@")], "excludeBannedUsers": True}).encode()
            d = json.loads(_get("https://users.roblox.com/v1/usernames/users", data=body,
                                headers={"Content-Type": "application/json", "Accept": "application/json"}))
            if d.get("data"):
                uid = str(d["data"][0]["id"])
        except Exception:
            uid = None
    if not uid:
        return None, None, s
    name = None
    try:
        info = _get_json(f"https://users.roblox.com/v1/users/{uid}")
        name = info.get("displayName") or info.get("name")
    except Exception:
        pass
    avatar = None
    try:
        th = _get_json("https://thumbnails.roblox.com/v1/users/avatar-headshot"
                       f"?userIds={uid}&size=420x420&format=Png&isCircular=false")
        if th.get("data"):
            avatar = th["data"][0].get("imageUrl")
    except Exception:
        avatar = None
    return name, avatar, f"https://www.roblox.com/users/{uid}/profile"


def _generic(s: str):
    url = s if s.startswith("http") else "https://" + s
    html = _get(url)
    return _meta(html, "og:title"), _meta(html, "og:image"), url


def fetch_profile(target: str, outdir, platform: str = "auto") -> dict:
    """Return {platform, name, avatar_url, avatar_file, profile_url}. Downloads avatar PNG."""
    plat = platform if platform != "auto" else _detect(target)
    handler = {"youtube": _youtube, "steam": _steam, "roblox": _roblox, "generic": _generic}[plat]
    name, avatar, purl = handler(target)
    saved = None
    if avatar:
        try:
            saved = _save_avatar(avatar, outdir)
        except Exception:
            saved = None
    return {"platform": plat, "name": name, "avatar_url": avatar,
            "avatar_file": saved, "profile_url": purl}


def fetch_channel(url_or_handle: str, outdir) -> dict:  # back-compat (YouTube)
    return fetch_profile(url_or_handle, outdir, platform="youtube")
