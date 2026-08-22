"""Burn captions into a video from an .srt, with readable presets.

SRT is converted to ASS with the video's real resolution written into the header, so
font sizes are true pixels at any resolution (libass otherwise assumes a 288px-tall
reference and scales SRT text up ~3.75x on 1080p).
"""
from __future__ import annotations

import re
from pathlib import Path

# ASS colours are &HAABBGGRR (BGR order, AA = 00 opaque).
STYLES = {
    "clean":  {"Fontname": "Bahnschrift", "Fontsize": 52, "PrimaryColour": "&H00FFFFFF",
               "OutlineColour": "&H00000000", "BorderStyle": 1, "Outline": 3, "Shadow": 1,
               "Bold": -1, "Alignment": 2, "MarginV": 60},
    "bold":   {"Fontname": "Impact", "Fontsize": 64, "PrimaryColour": "&H00FFFFFF",
               "OutlineColour": "&H00000000", "BorderStyle": 1, "Outline": 5, "Shadow": 2,
               "Bold": -1, "Alignment": 2, "MarginV": 70},
    "yellow": {"Fontname": "Impact", "Fontsize": 64, "PrimaryColour": "&H0000E5FF",
               "OutlineColour": "&H00000000", "BorderStyle": 1, "Outline": 5, "Shadow": 2,
               "Bold": -1, "Alignment": 2, "MarginV": 70},
    "box":    {"Fontname": "Bahnschrift", "Fontsize": 48, "PrimaryColour": "&H00FFFFFF",
               "OutlineColour": "&HB0000000", "BackColour": "&HB0000000", "BorderStyle": 3,
               "Outline": 8, "Shadow": 0, "Bold": -1, "Alignment": 2, "MarginV": 60},
    "top":    {"Fontname": "Bahnschrift", "Fontsize": 52, "PrimaryColour": "&H00FFFFFF",
               "OutlineColour": "&H00000000", "BorderStyle": 1, "Outline": 3, "Shadow": 1,
               "Bold": -1, "Alignment": 8, "MarginV": 60},
}

_FIELDS = ["Name", "Fontname", "Fontsize", "PrimaryColour", "SecondaryColour", "OutlineColour",
           "BackColour", "Bold", "Italic", "Underline", "StrikeOut", "ScaleX", "ScaleY",
           "Spacing", "Angle", "BorderStyle", "Outline", "Shadow", "Alignment",
           "MarginL", "MarginR", "MarginV", "Encoding"]

_DEFAULTS = {"Name": "Default", "Fontname": "Arial", "Fontsize": 52,
             "PrimaryColour": "&H00FFFFFF", "SecondaryColour": "&H000000FF",
             "OutlineColour": "&H00000000", "BackColour": "&H00000000",
             "Bold": 0, "Italic": 0, "Underline": 0, "StrikeOut": 0,
             "ScaleX": 100, "ScaleY": 100, "Spacing": 0, "Angle": 0,
             "BorderStyle": 1, "Outline": 3, "Shadow": 1, "Alignment": 2,
             "MarginL": 90, "MarginR": 90, "MarginV": 60, "Encoding": 1}

_TS = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def escape_path(p) -> str:
    """Escape a path for use INSIDE an ffmpeg filter argument (Windows-safe)."""
    s = str(Path(p).resolve()).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def _ass_time(h, m, s, ms) -> str:
    cs = int(round(int(ms.ljust(3, "0")) / 10))
    if cs > 99:
        cs, s = 0, int(s) + 1
    return f"{int(h)}:{int(m):02d}:{int(s):02d}.{cs:02d}"


def parse_srt(path):
    """Yield (start, end, text) with ASS-ready text (\\N line breaks)."""
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    for block in re.split(r"\r?\n\r?\n", raw.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        m = None
        idx = 0
        for i, l in enumerate(lines):
            m = _TS.search(l)
            if m:
                idx = i + 1
                break
        if not m:
            continue
        start = _ass_time(*m.group(1, 2, 3, 4))
        end = _ass_time(*m.group(5, 6, 7, 8))
        text = "\\N".join(lines[idx:]).replace("{", "(").replace("}", ")")
        text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)  # strip <i>/<b> tags
        if text:
            yield start, end, text


def srt_to_ass(srt_path, ass_path, width: int, height: int, style: str = "clean",
               size: int | None = None, color: str | None = None,
               margin: int | None = None) -> str:
    st = dict(_DEFAULTS)
    st.update(STYLES.get(style, STYLES["clean"]))
    st["Name"] = "Default"
    if size:
        st["Fontsize"] = size
    if margin is not None:
        st["MarginV"] = margin
    if color:
        c = color.lstrip("#")
        if len(c) == 6:  # RRGGBB -> &H00BBGGRR
            st["PrimaryColour"] = f"&H00{c[4:6]}{c[2:4]}{c[0:2]}".upper()

    head = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        f"Format: {', '.join(_FIELDS)}\n"
        f"Style: {','.join(str(st[f]) for f in _FIELDS)}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    body = "".join(f"Dialogue: 0,{s},{e},Default,,0,0,0,,{t}\n" for s, e, t in parse_srt(srt_path))
    Path(ass_path).write_text(head + body, encoding="utf-8")
    return str(ass_path)
