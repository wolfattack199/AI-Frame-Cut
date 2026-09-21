"""`debug` — turn a screen recording of a bug into something a programmer (or an AI) can read.

A contact sheet is useless when the bug is one red line in a log window. This extracts frames
at scene changes and on a steady interval, READS the text on each frame (local OCR with the
same Qwen2-VL model `critique` uses; falls back to a description-only report without it),
transcribes the user's narration, flags frames that contain error-looking text, and writes a
single timeline `report.md` next to the frames — so an agent reads one file and opens only
the flagged frames.

Output folder (next to the video, or --out):
    report.md         timeline: [mm:ss] narration · on-screen text · flags · frame path
    frames/f_NNN_mmss.png
    ocr.json          per-frame text, flags, scene-change markers
    transcript.txt    narration
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from ._ffmpeg import FFMPEG, ffmpeg, fmt_tc, probe, run

ERROR_WORDS = [
    "exception", "error", "failed", "failure", "crash", "crashed", "traceback", "stack trace", "caused by",
    "nullpointer", "null pointer", "classnotfound", "noclassdef", "nosuchmethod", "unsupportedoperation",
    "indexoutofbounds", "illegalstate", "illegalargument", "stackoverflow", "outofmemory", "out of memory",
    "cannot", "could not", "couldn't", "unable to", "not found", "missing", "invalid", "unexpected", "timeout",
    "timed out", "denied", "refused", "fatal", "severe", "warn", "warning", "panic", "abort", "segfault",
    "access violation", "undefined", "is not a function", "syntaxerror", "typeerror", "referenceerror",
    "exit code", "exited with", "mixin", "fabric", "forge", "neoforge", "mod loader", "incompatible", "duplicate mod",
    "fail", "fails", "broke", "broken", "not working", "doesn't work", "won't", "glitch", "bug", "freeze", "froze", "stuck", "lag",
]
STRONG = ["exception", "traceback", "caused by", "crash", "fatal", "stack trace", "exit code", "segfault", "access violation", "out of memory"]


def _scene_times(video: str, threshold: float) -> list[float]:
    proc = run([FFMPEG, "-hide_banner", "-i", str(video), "-filter:v", f"scale=480:-2,select='gt(scene,{threshold})',showinfo",
                "-an", "-f", "null", "-"], check=False)
    return sorted(set(float(t) for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr or "")))


def _phash(im) -> int:
    """Tiny perceptual hash so near-identical consecutive frames are skipped."""
    from PIL import Image
    g = im.convert("L").resize((9, 8), Image.BILINEAR)
    px = list(g.getdata()); bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


_ocr = None
def _ocr_model():
    global _ocr
    if _ocr is None:
        try:
            import torch
            from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
        except ImportError:
            return None
        from .critique import VLM
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = Qwen2VLForConditionalGeneration.from_pretrained(VLM, dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev)
        proc = AutoProcessor.from_pretrained(VLM, min_pixels=512 * 28 * 28, max_pixels=1280 * 28 * 28)
        _ocr = (model, proc, dev)
    return _ocr


def _read_text(im, max_tokens: int = 400) -> str:
    vlm = _ocr_model()
    if vlm is None:
        return ""
    import torch
    model, proc, dev = vlm
    q = ("Transcribe ALL text visible on this screen exactly as written — error messages, log lines, console output, "
         "dialog boxes, code, window titles, menu labels. Keep line breaks. Do not describe the image; output only the text. "
         "If there is no text, output NONE.")
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": q}]}]
    prompt = proc.apply_chat_template(msgs, add_generation_prompt=True)
    inputs = proc(text=[prompt], images=[im], return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False, repetition_penalty=1.15)
    txt = proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
    return _clean(txt)


def _clean(txt: str) -> str:
    """Drop NONE markers and collapse the small model's repetition loops (same line over and over)."""
    lines = [l.rstrip() for l in txt.splitlines()]
    lines = [l for l in lines if l.strip() and l.strip().upper() != "NONE"]
    if not lines:
        return ""
    out = []
    for l in lines:
        if out and l.strip() == out[-1].strip():
            continue
        out.append(l)
    uniq = {l.strip() for l in out}
    if len(lines) >= 6 and len(uniq) <= max(1, len(lines) // 4):
        return ""                                        # degenerate loop, not real screen text
    return chr(10).join(out)


def _flags(text: str) -> list[str]:
    t = text.lower()
    hits = [w for w in ERROR_WORDS if w in t]
    return sorted(set(hits), key=lambda w: (w not in STRONG, w))


def debug_video(video: str, out: str | None = None, every: float = 2.0, threshold: float = 0.25, max_frames: int = 90,
                ocr: bool = True, transcribe: bool = True, width: int = 1280, on_progress=None) -> str:
    from PIL import Image
    video = str(video)
    outdir = Path(out) if out else Path(video).with_suffix("") .parent / (Path(video).stem + "_debug")
    frames_dir = outdir / "frames"
    if outdir.exists():
        shutil.rmtree(outdir)
    frames_dir.mkdir(parents=True)

    info = probe(video)
    dur = float(info.get("duration") or 0)

    # 1) candidate timestamps: every N seconds + scene changes, capped
    times = set(round(t, 2) for t in _frange(0.0, dur, every))
    for t in _scene_times(video, threshold):
        times.add(round(t + 0.05, 2))          # just after the cut so the new screen is fully drawn
    times = sorted(t for t in times if 0 <= t < max(dur, 0.1))
    if len(times) > max_frames:               # thin evenly but always keep scene changes
        scenes = set(round(t + 0.05, 2) for t in _scene_times(video, threshold))
        step = max(1, len(times) // max_frames)
        times = sorted(set(times[::step]) | (scenes & set(times)))[:max_frames]

    # 2) extract, dedupe near-identical, OCR
    tmp = Path(tempfile.mkdtemp(prefix="afc_dbg_"))
    entries = []; last_hash = None; kept = 0
    try:
        for i, t in enumerate(times):
            raw = tmp / f"raw_{i:04d}.png"
            ffmpeg(["-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-vf", f"scale={width}:-2", str(raw)], check=False)
            if not raw.exists():
                continue
            im = Image.open(raw).convert("RGB")
            h = _phash(im)
            if last_hash is not None and _hamming(h, last_hash) <= 3:
                continue                           # same screen as the previous kept frame
            last_hash = h; kept += 1
            name = f"f_{kept:03d}_{int(t // 60):02d}m{int(t % 60):02d}s.png"
            dst = frames_dir / name
            im.save(dst)
            text = _read_text(im) if ocr else ""
            entries.append({"t": t, "tc": fmt_tc(t), "frame": str(dst), "text": text, "flags": _flags(text)})
            if on_progress:
                on_progress(kept, len(times), t, entries[-1]["flags"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 3) narration
    segments = []
    if transcribe:
        try:
            from .transcribe import transcribe_file
            res = transcribe_file(video, model_size="base", out_base=str(outdir / "narration"))
            segments = res.get("segments", []) if isinstance(res, dict) else []
        except SystemExit:
            segments = []
        except Exception:
            segments = []
    (outdir / "transcript.txt").write_text("\n".join(f"[{fmt_tc(s['start'])}] {s['text']}" for s in segments) or "(no speech detected)", encoding="utf-8")

    # 4) report
    (outdir / "ocr.json").write_text(json.dumps({"video": video, "duration": dur, "frames": entries, "narration": segments}, indent=2), encoding="utf-8")
    flagged = [e for e in entries if e["flags"]]
    said_flags = [s_ for s_ in segments if _flags(s_["text"])]
    lines = [f"# Bug recording report — {Path(video).name}", "",
             f"Duration {fmt_tc(dur)} · {len(entries)} distinct screens kept · {len(flagged)} with error-looking text · "
             f"{'OCR on' if ocr and _ocr is not None else 'OCR OFF (install the ai extra for on-screen text)'}", ""]
    if flagged:
        lines += ["## Look here first", ""]
        for e in flagged:
            strong = [f for f in e["flags"] if f in STRONG]
            lines.append(f"- **[{e['tc']}]** {', '.join(strong or e['flags'][:4])} → `{e['frame']}`")
        lines.append("")
    if said_flags:
        lines += ["## The user said (error words in narration)", ""]
        for s_ in said_flags:
            lines.append(f"- **[{fmt_tc(s_['start'])}]** {s_['text']!r}")
        lines.append("")
    lines += ["## Timeline", ""]
    si = 0
    for e in entries:
        said = []
        while si < len(segments) and segments[si]["start"] <= e["t"] + every:
            if segments[si]["end"] >= e["t"] - every:
                said.append(segments[si]["text"])
            si += 1
        lines.append(f"### [{e['tc']}] {'⚠ ' + ', '.join(e['flags'][:5]) if e['flags'] else ''}".rstrip())
        lines.append(f"frame: `{e['frame']}`")
        if said:
            lines.append(f"narration: *{' '.join(said)}*")
        if e["text"]:
            lines += ["```", e["text"][:2500], "```"]
        lines.append("")
    lines += ["## How to use this (for an AI agent)", "",
              "1. Read the **Look here first** frames with your image reader — they hold the actual error text.",
              "2. The OCR is a small local model: treat quoted text as *approximately* what's on screen; confirm exact "
              "class names / line numbers by opening the frame.",
              "3. Narration lines tell you what the user was doing at that moment.",
              "4. Full per-frame text is in `ocr.json`; every extracted screen is in `frames/`."]
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return str(outdir / "report.md")


def _frange(a: float, b: float, step: float):
    t = a
    while t < b:
        yield t
        t += step
