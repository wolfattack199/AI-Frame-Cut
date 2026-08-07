"""ffmpeg/ffprobe discovery, a safe (no-shell) runner, and probing helpers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _candidate_dirs() -> list[Path]:
    home = Path.home()
    return [
        home / ".local" / "bin",          # where the frameforge installer puts a static build
        home / "scoop" / "shims",
        Path("C:/ffmpeg/bin"),
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]


def find_exe(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    win = name + (".exe" if os.name == "nt" else "")
    for d in _candidate_dirs():
        p = d / win
        if p.exists():
            return str(p)
    return None


FFMPEG = find_exe("ffmpeg")
FFPROBE = find_exe("ffprobe")


def _require(exe: str | None, name: str) -> str:
    if not exe:
        sys.exit(
            f"[frameforge] '{name}' was not found. Install ffmpeg and make sure it is on "
            f"your PATH (or in ~/.local/bin). Run 'frameforge doctor' for details."
        )
    return exe


def run(args: list, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command given as a list of args, with no shell (robust quoting)."""
    args = [str(a) for a in args]
    proc = subprocess.run(args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").splitlines()[-15:])
        sys.exit(f"[frameforge] command failed (exit {proc.returncode}):\n"
                 f"  {' '.join(args[:8])} ...\n{tail}")
    return proc


def ffmpeg(args: list, check: bool = True) -> subprocess.CompletedProcess:
    return run([_require(FFMPEG, "ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args], check=check)


def ffprobe_json(path) -> dict:
    exe = _require(FFPROBE, "ffprobe")
    proc = run([exe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    return json.loads(proc.stdout or "{}")


def _fps_of(stream: dict) -> float:
    r = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        n, d = r.split("/")
        return round(float(n) / float(d), 3) if float(d) else 0.0
    except Exception:
        return 0.0


def probe(path) -> dict:
    """Return a compact dict of the key facts about a media file."""
    if not Path(path).exists():
        sys.exit(f"[frameforge] file not found: {path}")
    data = ffprobe_json(path)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    return {
        "path": str(path),
        "duration": float(fmt.get("duration", 0) or 0),
        "size_mb": round(int(fmt.get("size", 0) or 0) / 1048576, 1),
        "width": int(v.get("width", 0) or 0),
        "height": int(v.get("height", 0) or 0),
        "fps": _fps_of(v),
        "vcodec": v.get("codec_name"),
        "pix_fmt": v.get("pix_fmt"),
        "acodec": a.get("codec_name"),
        "channels": a.get("channels"),
        "sample_rate": a.get("sample_rate"),
        "has_audio": bool(a),
    }


def fmt_tc(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def default_out(video, suffix: str) -> str:
    p = Path(video)
    return str(p.with_name(p.stem + suffix))


def grab_frame(video, t: float, out, width: int | None = None):
    """Grab a single frame near timestamp `t` using a fast keyframe seek.

    `-ss` before `-i` seeks to the nearest keyframe (sub-second), so this stays
    fast even on long 4K files — ideal for sparse sampling (contact sheets)."""
    pre = ["-ss", str(max(0.0, t)), "-i", str(video), "-frames:v", "1"]
    if width:
        pre += ["-vf", f"scale={width}:-2"]
    ffmpeg([*pre, str(out)])
