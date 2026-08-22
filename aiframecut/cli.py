"""aiframecut command-line interface."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from . import __version__
from ._ffmpeg import (FFMPEG, FFPROBE, ffmpeg, probe, fmt_tc, default_out, run, grab_frame)
from .captions import STYLES as CAPTION_STYLES, escape_path as _esc_sub, srt_to_ass
from .titles import build_contact_sheet, make_title_card
from .thumbnail import make_thumbnail
from .transcribe import transcribe_file
from .web import fetch_profile

# One-word color grades. Each value is an ffmpeg filter chain (no scaling/letterbox;
# those are added by the grade command from flags).
LOOKS = {
    "cinematic": ("eq=contrast=1.10:saturation=0.97:gamma=1.05:brightness=0.015,"
                  "colorbalance=rs=-0.03:bs=0.06:rh=0.06:bh=-0.04,vignette=PI/6,noise=alls=5:allf=t"),
    "noir":      "hue=s=0,eq=contrast=1.28:brightness=-0.02,noise=alls=8:allf=t,vignette=PI/5",
    "warm":      "eq=contrast=1.06:saturation=1.08,colorbalance=rh=0.08:rm=0.04:bs=-0.05,vignette=PI/6.5",
    "cold":      "eq=contrast=1.08:saturation=0.98,colorbalance=bs=0.09:bh=0.05:rs=-0.05,vignette=PI/6.5",
    "vhs":       "eq=contrast=1.05:saturation=1.15,gblur=sigma=0.4,noise=alls=12:allf=t+u,vignette=PI/5",
    "clean":     "eq=contrast=1.04:saturation=1.02",
}

# --quality presets: (crf/cq, preset). Lower crf = higher quality/larger.
_Q_X264 = {"max": (16, "slow"), "high": (18, "medium"), "balanced": (20, "medium"), "fast": (23, "veryfast")}
_Q_NVENC = {"max": (18, "p7"), "high": (20, "p6"), "balanced": (23, "p5"), "fast": (26, "p4")}


def VENC(a):
    """Video-encode flags. `--quality` sets crf/preset; `--gpu` uses NVENC; `--keyint`
    sets a denser keyframe interval (seconds) for precise cuts + smoother seeking."""
    q = getattr(a, "quality", None)
    if getattr(a, "gpu", False):
        cq, preset = _Q_NVENC.get(q, (a.crf, "p5"))
        v = ["-c:v", "h264_nvenc", "-preset", preset, "-rc", "vbr", "-cq", str(cq), "-pix_fmt", "yuv420p"]
    else:
        crf, preset = _Q_X264.get(q, (a.crf, a.preset))
        v = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    ki = getattr(a, "keyint", None)
    if ki and getattr(a, "video", None):
        try:
            fps = probe(a.video)["fps"] or 30
            v += ["-g", str(max(1, int(round(fps * ki))))]
        except Exception:
            pass
    return v


def INDEC(a):
    """Input decode flags — `--gpu` decodes on the GPU too (full NVDEC->NVENC pipeline)."""
    return ["-hwaccel", "cuda"] if getattr(a, "gpu", False) else []


AENC = ["-c:a", "aac", "-b:a", "160k"]

# Voice-changer pitch factors (<1 = deeper, >1 = higher).
VOICES = {"deep": 0.82, "deeper": 0.72, "high": 1.25, "chipmunk": 1.5}


def _pitch_af(video, factor: float) -> str:
    sr = int(probe(video)["sample_rate"] or 48000)
    # resample to shift pitch, then restore the original duration/tempo
    steps = [f"asetrate={int(sr * factor)}", f"aresample={sr}"]
    t = 1.0 / factor
    while t > 2.0:
        steps.append("atempo=2.0"); t /= 2.0
    while t < 0.5:
        steps.append("atempo=0.5"); t /= 0.5
    steps.append(f"atempo={t:.4f}")
    return ",".join(steps)


def _letterbox_filters(frac: float) -> list[str]:
    return [f"drawbox=y=0:w=iw:h=ih*{frac}:color=black:t=fill",
            f"drawbox=y=ih*(1-{frac}):w=iw:h=ih*{frac}:color=black:t=fill"]


def _print(d):
    print(json.dumps(d, indent=2) if isinstance(d, (dict, list)) else d)


# ------------------------------------------------------------- commands ----
def cmd_doctor(a):
    print(f"aiframecut {__version__}")
    print(f"python     {sys.version.split()[0]}")
    print(f"ffmpeg     {FFMPEG or 'NOT FOUND'}")
    print(f"ffprobe    {FFPROBE or 'NOT FOUND'}")
    try:
        import PIL
        print(f"pillow     {PIL.__version__}")
    except Exception:
        print("pillow     NOT INSTALLED")
    try:
        import faster_whisper
        print(f"whisper    faster-whisper {getattr(faster_whisper, '__version__', 'installed')}")
    except Exception:
        print("whisper    NOT INSTALLED (transcription off — run 'uv sync')")
    gpu = "none (CPU encoding). Add --gpu only if an NVIDIA encoder shows here."
    if FFMPEG and "h264_nvenc" in run([FFMPEG, "-hide_banner", "-encoders"], check=False).stdout:
        gpu = "h264_nvenc available — pass --gpu for fast encoding"
    print(f"gpu enc    {gpu}")
    if FFMPEG:
        v = run([FFMPEG, "-version"]).stdout.splitlines()[0]
        print(f"           {v}")
    print("looks     ", ", ".join(LOOKS))
    print("title     ", "horror, clean, glitch, warm")
    print("voices    ", ", ".join(list(VOICES) + ["radio", "robot", "denoise", "clean"]))


def cmd_probe(a):
    info = probe(a.video)
    if a.json:
        _print(info)
        return
    print(f"{Path(info['path']).name}")
    print(f"  duration : {fmt_tc(info['duration'])}  ({info['duration']:.2f}s)")
    print(f"  video    : {info['width']}x{info['height']} @ {info['fps']}fps  "
          f"{info['vcodec']} {info['pix_fmt']}")
    print(f"  audio    : {('%s %sch %sHz' % (info['acodec'], info['channels'], info['sample_rate'])) if info['has_audio'] else 'none'}")
    print(f"  size     : {info['size_mb']} MB")


def cmd_contact(a):
    info = probe(a.video)
    dur = info["duration"]
    start = a.start or 0.0
    end = a.end if a.end is not None else dur
    window = max(0.05, end - start)
    if a.every:
        interval = a.every
        count = max(1, int(window // interval) + 1)
    else:
        count = max(1, a.count)
        interval = window / count
    tmp = Path(tempfile.mkdtemp(prefix="ff_contact_"))
    try:
        cap = max(0.0, dur - 0.05)
        for i in range(count):
            grab_frame(a.video, min(start + i * interval, cap),
                       tmp / f"f_{i:04d}.png", a.tile_width)
        frames = sorted(tmp.glob("f_*.png"))
        out = a.out or default_out(a.video, "_contact.png")
        build_contact_sheet(frames, out, cols=a.cols, start=start, interval=interval)
        print(f"contact sheet -> {out}")
        print(f"  {len(frames)} frames, 1 every {interval:.1f}s, {a.cols} cols "
              f"(tile {a.tile_width}px). Cell timecodes are stamped top-left.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_frames(a):
    outdir = Path(a.out or default_out(a.video, "_frames"))
    outdir.mkdir(parents=True, exist_ok=True)
    info = probe(a.video)
    start = a.start or 0.0
    end = a.end if a.end is not None else info["duration"]
    window = max(0.05, end - start)
    if a.count:  # N evenly-spaced frames — fast keyframe seeks
        interval = window / a.count
        for i in range(a.count):
            grab_frame(a.video, start + i * interval, outdir / f"frame_{i:05d}.png", a.width)
        n = a.count
    else:  # dense extraction at a real fps — needs a full decode pass
        vf = f"fps={a.fps}" + (f",scale={a.width}:-2" if a.width else "")
        ffmpeg(["-ss", str(start), "-i", str(a.video), "-t", str(window),
                "-vf", vf, str(outdir / "frame_%05d.png")])
        n = len(list(outdir.glob("frame_*.png")))
    print(f"extracted {n} frames -> {outdir}")


def cmd_thumb(a):
    out = a.out or default_out(a.video, f"_t{a.at:g}.png")
    pre = ["-ss", str(a.at), "-i", str(a.video), "-frames:v", "1"]
    if a.width:
        pre += ["-vf", f"scale={a.width}:-2"]
    ffmpeg([*pre, out])
    print(f"thumb @ {fmt_tc(a.at)} -> {out}")


def cmd_grade(a):
    look = LOOKS.get(a.look)
    if look is None:
        sys.exit(f"[aiframecut] unknown look '{a.look}'. options: {', '.join(LOOKS)}")
    chain = []
    if a.height:
        chain.append(f"scale=-2:{a.height}:flags=lanczos")
    chain.append(look)
    if a.letterbox and a.letterbox > 0:
        chain += _letterbox_filters(a.letterbox)
    out = a.out or default_out(a.video, f"_{a.look}.mp4")
    args = [*INDEC(a), "-i", str(a.video), "-vf", ",".join(chain), *VENC(a)]
    if a.fps:
        args += ["-r", str(a.fps)]
    args += [*AENC, out]
    ffmpeg(args)
    print(f"graded '{a.look}'"
          + (f", {a.height}p" if a.height else "")
          + (f", letterbox {a.letterbox}" if a.letterbox else "")
          + f" -> {out}")


def cmd_trim(a):
    out = a.out or default_out(a.video, "_trim.mp4")
    dur = None if a.end is None else max(0.02, a.end - a.start)
    args = ["-ss", str(a.start), "-i", str(a.video)]
    if dur is not None:
        args += ["-t", str(dur)]
    if a.reencode:
        args += [*VENC(a), *AENC]
        mode = "re-encode (frame-accurate)"
    else:
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        mode = "keyframe copy (instant)"
    args += [out]
    ffmpeg(args)
    print(f"trim {fmt_tc(a.start)}..{fmt_tc(a.end) if a.end is not None else 'end'} [{mode}] -> {out}")


def _parse_segments(spec: str) -> list[tuple[float, float]]:
    segs = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            sys.exit(f"[aiframecut] bad segment '{part}', expected START-END (e.g. 12-30)")
        a_s, b_s = part.split("-", 1)
        segs.append((float(a_s), float(b_s)))
    if not segs:
        sys.exit("[aiframecut] no segments given")
    return segs


def cmd_cut(a):
    segs = _parse_segments(a.keep)
    has_audio = probe(a.video)["has_audio"]
    parts, labels = [], []
    for i, (s, e) in enumerate(segs):
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        else:
            labels.append(f"[v{i}]")
    n = len(segs)
    if has_audio:
        parts.append("".join(labels) + f"concat=n={n}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]", *AENC]
    else:
        parts.append("".join(labels) + f"concat=n={n}:v=1:a=0[v]")
        maps = ["-map", "[v]"]
    out = a.out or default_out(a.video, "_cut.mp4")
    ffmpeg([*INDEC(a), "-i", str(a.video), "-filter_complex", ";".join(parts), *maps, *VENC(a), out])
    kept = sum(e - s for s, e in segs)
    print(f"kept {n} segment(s) ({kept:.1f}s total) -> {out}")


def cmd_concat(a):
    clips = a.clips
    for c in clips:
        if not Path(c).exists():
            sys.exit(f"[aiframecut] clip not found: {c}")
    infos = [probe(c) for c in clips]
    key = lambda i: (i["width"], i["height"], i["fps"], i["vcodec"], i["acodec"], i["has_audio"])
    same = all(key(i) == key(infos[0]) for i in infos)
    out = a.out
    if same and not a.reencode:
        fd, lst = tempfile.mkstemp(suffix=".txt")
        os.close(fd)  # release the handle so Windows lets us unlink it later
        Path(lst).write_text("".join(f"file '{Path(c).resolve().as_posix()}'\n" for c in clips))
        ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
        Path(lst).unlink(missing_ok=True)
        print(f"concat {len(clips)} clips [stream copy] -> {out}")
    else:
        h = infos[0]["height"] or 1080
        fps = infos[0]["fps"] or 30
        any_audio = any(i["has_audio"] for i in infos)
        ins, parts, labels = [], [], []
        for idx, c in enumerate(clips):
            ins += ["-i", str(c)]
            parts.append(f"[{idx}:v]scale=-2:{h},fps={fps},setsar=1,format=yuv420p[v{idx}]")
            if any_audio:
                if infos[idx]["has_audio"]:
                    parts.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo[a{idx}]")
                else:
                    parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{infos[idx]['duration']:.3f}[a{idx}]")
                labels.append(f"[v{idx}][a{idx}]")
            else:
                labels.append(f"[v{idx}]")
        if any_audio:
            parts.append("".join(labels) + f"concat=n={len(clips)}:v=1:a=1[v][a]")
            maps = ["-map", "[v]", "-map", "[a]", *AENC]
        else:
            parts.append("".join(labels) + f"concat=n={len(clips)}:v=1:a=0[v]")
            maps = ["-map", "[v]"]
        ffmpeg([*ins, "-filter_complex", ";".join(parts), *maps, *VENC(a), out])
        print(f"concat {len(clips)} clips [re-encode {h}p/{fps}fps] -> {out}")


def _atempo_chain(factor: float) -> str:
    f = factor
    parts = []
    while f > 2.0:
        parts.append("atempo=2.0"); f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5"); f /= 0.5
    parts.append(f"atempo={f:.4f}")
    return ",".join(parts)


def cmd_speed(a):
    out = a.out or default_out(a.video, "_speed.mp4")
    has_audio = probe(a.video)["has_audio"]
    if has_audio and not a.mute:
        fc = f"[0:v]setpts=PTS/{a.factor}[v];[0:a]{_atempo_chain(a.factor)}[a]"
        maps = ["-map", "[v]", "-map", "[a]", *AENC]
    else:
        fc = f"[0:v]setpts=PTS/{a.factor}[v]"
        maps = ["-map", "[v]"]
    ffmpeg([*INDEC(a), "-i", str(a.video), "-filter_complex", fc, *maps, *VENC(a), out])
    print(f"speed x{a.factor} -> {out}")


def cmd_resize(a):
    out = a.out or default_out(a.video, f"_{a.height or a.width}.mp4")
    if a.height:
        vf = f"scale=-2:{a.height}:flags=lanczos"
    else:
        vf = f"scale={a.width}:-2:flags=lanczos"
    ffmpeg([*INDEC(a), "-i", str(a.video), "-vf", vf, *VENC(a), "-c:a", "copy", out])
    print(f"resized -> {out}")


def cmd_audio(a):
    out = a.out or default_out(a.video, ".mp3")
    ffmpeg(["-i", str(a.video), "-vn", "-c:a", "libmp3lame", "-q:a", "2", out])
    print(f"audio -> {out}")


def cmd_gif(a):
    out = a.out or default_out(a.video, ".gif")
    start = a.start or 0.0
    dur = (a.end - start) if a.end is not None else 4.0
    vf = f"fps={a.fps},scale={a.width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    ffmpeg(["-ss", str(start), "-t", str(dur), "-i", str(a.video), "-filter_complex", vf, out])
    print(f"gif ({dur:.1f}s @ {a.fps}fps) -> {out}")


def cmd_title(a):
    make_title_card(a.out, text=a.text, sub=a.sub or "", seconds=a.seconds,
                    style=a.style, size=tuple(int(x) for x in a.size.lower().split("x")),
                    fps=a.fps, letterbox=a.letterbox,
                    flicker=(None if a.flicker == "auto" else a.flicker == "on"),
                    audio=not a.silent, crf=a.crf, preset=a.preset,
                    logo=a.logo, cta=a.cta)
    print(f"title card '{a.text}' ({a.seconds:g}s, style {a.style})"
          + (", +logo" if a.logo else "") + (f", cta '{a.cta}'" if a.cta else "")
          + f" -> {a.out}")


def cmd_preview(a):
    """Fast, small, low-res proxy so the user can quickly SEE the current state."""
    out = a.out or default_out(a.video, "_preview.mp4")
    ffmpeg(["-i", str(a.video), "-vf", f"scale=-2:{a.height}:flags=bilinear",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(a.crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", out])
    mb = Path(out).stat().st_size / 1048576
    print(f"preview ({a.height}p, fast proxy) -> {out}  ({mb:.1f} MB)")


def cmd_music(a):
    """Mix a background music track under the video (optional ducking under speech)."""
    if not Path(a.track).exists():
        sys.exit(f"[aiframecut] music track not found: {a.track}")
    out = a.out or default_out(a.video, "_music.mp4")
    info = probe(a.video)
    vdur = info["duration"]
    m = [f"volume={a.volume}"]
    if a.fade > 0:
        m.append(f"afade=t=in:st=0:d={a.fade}")
        m.append(f"afade=t=out:st={max(0.1, vdur - a.fade):.2f}:d={a.fade}")
    mchain = ",".join(m)
    if info["has_audio"] and a.duck:
        fc = (f"[1:a]{mchain}[m];"
              f"[m][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[md];"
              f"[0:a][md]amix=inputs=2:duration=first:dropout_transition=0,volume=1.5[a]")
    elif info["has_audio"]:
        fc = f"[1:a]{mchain}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]"
    else:
        fc = f"[1:a]{mchain}[a]"
    ffmpeg(["-i", str(a.video), "-stream_loop", "-1", "-i", str(a.track),
            "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", out])
    print(f"music mixed{' (ducked under speech)' if (a.duck and info['has_audio']) else ''} -> {out}")


def cmd_profile(a):
    """Grab a PUBLIC profile avatar + name (YouTube / Steam / Roblox / any og:image). No API key."""
    outdir = a.out or "channel_assets"
    res = fetch_profile(a.target, outdir, platform=a.platform)
    print(f"platform: {res['platform']}")
    print(f"name:     {res['name'] or '(not found)'}")
    print(f"url:      {res['profile_url']}")
    if res["avatar_file"]:
        print(f"avatar:   {res['avatar_file']}")
        nm = (res["name"] or "MY CHANNEL").upper()
        print("\nUse it in a branded card:")
        print(f'  aiframecut title --text "{nm}" --cta "SUBSCRIBE & LIKE" '
              f'--logo "{res["avatar_file"]}" --style clean --seconds 5 -o outro.mp4')
    else:
        print("avatar:   (couldn't fetch a public avatar for that profile)")


def _parse_color(s: str):
    s = (s or "").lstrip("#").strip()
    named = {"red": "e6283c", "blue": "2b7cff", "green": "1fbf5a", "yellow": "ffcf33",
             "orange": "ff7a1a", "purple": "9b4dff", "pink": "ff4d94", "cyan": "28c8d2",
             "white": "f2f2f2"}
    s = named.get(s.lower(), s)
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (230, 40, 60)


def cmd_thumbnail(a):
    info = probe(a.video)
    at = a.at if a.at is not None else info["duration"] / 2
    tmp = Path(tempfile.mkdtemp(prefix="afc_thumb_"))
    try:
        frame = str(tmp / "frame.png")
        grab_frame(a.video, at, frame)
        out = a.out or default_out(a.video, "_thumb.png")
        make_thumbnail(out, frame, a.text, sub=a.sub or "", logo=a.logo, accent=_parse_color(a.accent))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"thumbnail (1280x720, frame @ {fmt_tc(at)}) -> {out}")


def cmd_inspect(a):
    """WATCH-FIRST bundle: spec + contact sheet + scene count + a review checklist."""
    info = probe(a.video)
    print("=== SPEC ===")
    print(f"{Path(info['path']).name}  {fmt_tc(info['duration'])}  "
          f"{info['width']}x{info['height']}@{info['fps']}fps  audio={'yes' if info['has_audio'] else 'no'}")
    out = a.out or default_out(a.video, "_contact.png")
    dur = info["duration"]
    interval = dur / max(1, a.count)
    tmp = Path(tempfile.mkdtemp(prefix="afc_inspect_"))
    try:
        cap = max(0.0, dur - 0.05)
        for i in range(a.count):
            grab_frame(a.video, min(i * interval, cap), tmp / f"f_{i:04d}.png", 320)
        build_contact_sheet(sorted(tmp.glob("f_*.png")), out, cols=6, start=0, interval=interval)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"=== CONTACT SHEET ===\n{out}   <- Read this image; actually LOOK at the video")
    if FFMPEG:
        proc = run([FFMPEG, "-hide_banner", "-i", str(a.video),
                    "-filter:v", "scale=480:-2,select='gt(scene,0.3)',showinfo",
                    "-an", "-f", "null", "-"], check=False)
        n = len(set(re.findall(r"pts_time:([0-9.]+)", proc.stderr or "")))
        print(f"=== SCENES === ~{n} scene changes")
    print("""
=== WATCH-FIRST CHECKLIST (do this BEFORE asking how to edit) ===
1. READ the contact sheet above — really look at every tile.
2. FLAG anything to remove: passwords / login screens, real names, emails, phone numbers,
   home address, OBS or streamer dashboards, other people, private browser tabs, DMs.
3. NOTE obvious fixes: dead air / long pauses, menus or loading at the start, weak opening.
4. If there is speech, run `transcribe` to read it (and catch spoken 'edit this out').
THEN tell the user what you SAW and let them choose what to do (remove the sensitive stuff?
add captions? cut the boring parts? intro/outro? music?) — don't edit until they pick.""")


def cmd_transcribe(a):
    triggers = None
    if a.find:
        triggers = [t.strip().lower() for t in a.find.split(",") if t.strip()]
    print(f"transcribing with local Whisper '{a.model}' (no API key; first run downloads the model)...")
    res = transcribe_file(a.video, model_size=a.model, language=a.lang, out_base=a.out,
                          triggers=triggers, device=a.device,
                          compute_type=("float16" if a.device == "cuda" else "int8"))
    print(f"language: {res['language']} ({res['language_probability']}), "
          f"{res['duration']}s, {len(res['segments'])} segments")
    print(f"wrote {res['_out_base']}.srt / .txt / .json")
    marks = res["edit_marks"]
    if marks:
        print(f"\n{len(marks)} spoken EDIT mark(s):")
        for m in marks:
            print(f"  @ {fmt_tc(m['at'])}  \"{m['said']}\"  -> suggest cutting {m['suggested_cut']}")
    else:
        print("no spoken edit-words found.")


def cmd_voice(a):
    out = a.out or default_out(a.video, f"_{a.effect}.mp4")
    if a.effect in VOICES:
        af = _pitch_af(a.video, VOICES[a.effect])
    elif a.effect == "radio":
        af = "highpass=f=300,lowpass=f=3400,acompressor,volume=1.6"
    elif a.effect == "robot":
        sr = int(probe(a.video)["sample_rate"] or 48000)
        af = f"asetrate={int(sr * 0.9)},aresample={sr},atempo={1 / 0.9:.4f},aphaser=speed=2,flanger"
    elif a.effect == "denoise":
        af = "afftdn=nf=-25"
    elif a.effect == "clean":
        af = "afftdn=nf=-20,acompressor=threshold=-18dB:ratio=3,loudnorm"
    else:
        sys.exit(f"[aiframecut] unknown voice effect '{a.effect}'")
    if a.volume != 1.0:
        af += f",volume={a.volume}"
    # video stream is copied (instant) — only the audio is re-encoded
    ffmpeg(["-i", str(a.video), "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", out])
    print(f"voice '{a.effect}' applied (video copied, audio only) -> {out}")


def cmd_scenes(a):
    if not FFMPEG:
        sys.exit("[aiframecut] ffmpeg not found")
    # decode a downscaled copy for speed; showinfo prints pts_time for each scene-cut frame
    proc = run([FFMPEG, "-hide_banner", "-i", str(a.video),
                "-filter:v", f"scale=480:-2,select='gt(scene,{a.threshold})',showinfo",
                "-an", "-f", "null", "-"], check=False)
    times = sorted(set(float(t) for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr or "")))
    print(f"{len(times)} scene change(s) at threshold {a.threshold}:")
    for t in times:
        print(f"  {fmt_tc(t)}  ({t:.2f}s)")
    if not times:
        print("  (none found — try a lower --threshold, e.g. 0.2)")


def cmd_short(a):
    """Convert a clip to a vertical 9:16 YouTube Short / Reel (blurred pad or crop)."""
    info = probe(a.video)
    start = a.start or 0.0
    end = a.end if a.end is not None else info["duration"]
    dur = min(max(0.1, end - start), a.max)
    if a.mode == "crop":
        fc = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v]"
    else:  # pad — whole frame stays visible over a blurred fill
        fc = ("[0:v]split=2[bg][fg];"
              "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=22[b];"
              "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[f];"
              "[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    out = a.out or default_out(a.video, "_short.mp4")
    ffmpeg([*INDEC(a), "-ss", str(start), "-i", str(a.video), "-t", str(dur),
            "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", *VENC(a), *AENC, out])
    print(f"short (1080x1920, {a.mode}, {dur:.1f}s) -> {out}")
    if a.title or a.tags or a.desc:
        meta = Path(out).with_suffix(".txt")
        blocks = []
        if a.title:
            blocks.append("TITLE:\n" + a.title)
        if a.tags:
            blocks.append("TAGS:\n" + ", ".join(t.strip() for t in a.tags.split(",")))
        if a.desc:
            blocks.append("DESCRIPTION:\n" + a.desc)
        meta.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        print(f"metadata -> {meta}")


def cmd_split(a):
    """Split a long video into chunks + a manifest, so an AI can work through it piece by piece."""
    dur = probe(a.video)["duration"]
    seg = (dur / a.parts) if a.parts else (a.minutes * 60)
    outdir = Path(a.out or default_out(a.video, "_chunks"))
    outdir.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-i", str(a.video), "-c", "copy", "-map", "0", "-f", "segment",
            "-segment_time", f"{seg:.3f}", "-reset_timestamps", "1",
            str(outdir / "chunk_%03d.mp4")])
    chunks = sorted(outdir.glob("chunk_*.mp4"))
    lines, t = [], 0.0
    for c in chunks:
        d = probe(c)["duration"]
        lines.append(f"{c.name}\t{fmt_tc(t)}-{fmt_tc(t + d)}\t{d:.1f}s")
        t += d
    (outdir / "chunks.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"split into {len(chunks)} chunks (~{seg / 60:.1f} min each) -> {outdir}")
    for ln in lines:
        print("  " + ln)
    print("\nWork through them: `inspect` / `transcribe` each chunk, pick the good parts, "
          "then `cut` / `concat` the keepers.")


def cmd_captions(a):
    """Burn captions into the video from an .srt (auto-transcribes first if none given)."""
    srt = a.srt
    if not srt:
        base = str(Path(default_out(a.video, "")).with_suffix(""))
        cand = Path(base + ".srt")
        if cand.exists() and not a.force:
            srt = str(cand)
            print(f"using existing transcript: {srt}")
        else:
            print(f"no .srt given — transcribing locally with Whisper '{a.model}' first...")
            res = transcribe_file(a.video, model_size=a.model, language=a.lang)
            srt = res["_out_base"] + ".srt"
    if not Path(srt).exists():
        sys.exit(f"[aiframecut] subtitle file not found: {srt}")
    out = a.out or default_out(a.video, "_cap.mp4")
    info = probe(a.video)
    tmp = Path(tempfile.mkdtemp(prefix="afc_cap_"))
    try:
        # convert to ASS carrying the real frame size, so --size is in true pixels
        ass = srt_to_ass(srt, tmp / "subs.ass", info["width"] or 1920, info["height"] or 1080,
                         style=a.style, size=a.size, color=a.color, margin=a.margin)
        ffmpeg([*INDEC(a), "-i", str(a.video), "-vf", f"ass='{_esc_sub(ass)}'",
                *VENC(a), "-c:a", "copy", out])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"captions burned in (style '{a.style}') -> {out}")


def cmd_smooth(a):
    """Motion-interpolate to a higher framerate for buttery-smooth motion (slow, real work)."""
    out = a.out or default_out(a.video, f"_{int(a.fps)}fps.mp4")
    vf = f"minterpolate=fps={a.fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    if a.height:
        vf += f",scale=-2:{a.height}:flags=lanczos"
    ffmpeg([*INDEC(a), "-i", str(a.video), "-vf", vf, *VENC(a), "-c:a", "copy", out])
    print(f"smoothed to {a.fps}fps (motion-interpolated) -> {out}")


# --------------------------------------------------------------- parser ----
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aiframecut",
        description="AI Frame Cut — give Claude & ChatGPT eyes, ears, and fast hands for video.")
    p.add_argument("--version", action="version", version=f"aiframecut {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def enc(sp):  # shared encode flags
        sp.add_argument("--crf", type=int, default=20)
        sp.add_argument("--preset", default="medium")
        sp.add_argument("--quality", choices=["max", "high", "balanced", "fast"],
                        help="quality preset (max = near-lossless, slow). Overrides --crf/--preset.")
        sp.add_argument("--keyint", type=float,
                        help="keyframe interval in seconds (denser = more precise cuts + seeking)")
        sp.add_argument("--gpu", action="store_true",
                        help="NVIDIA GPU decode + NVENC encode (full hardware pipeline)")

    sp = sub.add_parser("doctor", help="check ffmpeg/ffprobe/pillow and list looks")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("probe", help="print a video's specs")
    sp.add_argument("video"); sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("contact", help="labeled contact sheet of a whole video (SEE it at a glance)")
    sp.add_argument("video"); sp.add_argument("-o", "--out")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--count", type=int, default=30, help="number of frames (default 30)")
    g.add_argument("--every", type=float, help="one frame every N seconds")
    sp.add_argument("--cols", type=int, default=6)
    sp.add_argument("--tile-width", type=int, default=320, dest="tile_width")
    sp.add_argument("--start", type=float, default=0.0); sp.add_argument("--end", type=float)
    sp.set_defaults(func=cmd_contact)

    sp = sub.add_parser("frames", help="extract frames at any fps or N evenly-spaced")
    sp.add_argument("video"); sp.add_argument("-o", "--out")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--fps", type=float, default=1.0)
    g.add_argument("--count", type=int)
    sp.add_argument("--width", type=int); sp.add_argument("--start", type=float, default=0.0)
    sp.add_argument("--end", type=float)
    sp.set_defaults(func=cmd_frames)

    sp = sub.add_parser("thumb", help="one frame at a timestamp")
    sp.add_argument("video"); sp.add_argument("--at", type=float, required=True)
    sp.add_argument("-o", "--out"); sp.add_argument("--width", type=int)
    sp.set_defaults(func=cmd_thumb)

    sp = sub.add_parser("grade", help="apply a one-word cinematic look")
    sp.add_argument("video"); sp.add_argument("--look", default="cinematic", choices=list(LOOKS))
    sp.add_argument("-o", "--out"); sp.add_argument("--height", type=int, help="downscale, e.g. 1080")
    sp.add_argument("--letterbox", type=float, default=0.0, help="bar height fraction, e.g. 0.07")
    sp.add_argument("--fps", type=float); enc(sp)
    sp.set_defaults(func=cmd_grade)

    sp = sub.add_parser("trim", help="cut one span (keyframe-instant by default)")
    sp.add_argument("video"); sp.add_argument("--start", type=float, required=True)
    sp.add_argument("--end", type=float); sp.add_argument("-o", "--out")
    sp.add_argument("--reencode", action="store_true", help="frame-accurate (slower)"); enc(sp)
    sp.set_defaults(func=cmd_trim)

    sp = sub.add_parser("cut", help="keep+join highlight segments, e.g. --keep 5-12,40-55")
    sp.add_argument("video"); sp.add_argument("--keep", required=True)
    sp.add_argument("-o", "--out"); enc(sp)
    sp.set_defaults(func=cmd_cut)

    sp = sub.add_parser("concat", help="join clips (stream-copy if compatible, else re-encode)")
    sp.add_argument("out"); sp.add_argument("clips", nargs="+")
    sp.add_argument("--reencode", action="store_true"); enc(sp)
    sp.set_defaults(func=cmd_concat)

    sp = sub.add_parser("speed", help="speed up / slow down (audio pitch-preserved)")
    sp.add_argument("video"); sp.add_argument("--factor", type=float, required=True)
    sp.add_argument("--mute", action="store_true"); sp.add_argument("-o", "--out"); enc(sp)
    sp.set_defaults(func=cmd_speed)

    sp = sub.add_parser("resize", help="scale to a height (or width)")
    sp.add_argument("video")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--height", type=int); g.add_argument("--width", type=int)
    sp.add_argument("-o", "--out"); enc(sp)
    sp.set_defaults(func=cmd_resize)

    sp = sub.add_parser("audio", help="extract audio to mp3")
    sp.add_argument("video"); sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_audio)

    sp = sub.add_parser("gif", help="make a gif from a span")
    sp.add_argument("video"); sp.add_argument("--start", type=float, default=0.0)
    sp.add_argument("--end", type=float); sp.add_argument("--fps", type=int, default=15)
    sp.add_argument("--width", type=int, default=480); sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_gif)

    sp = sub.add_parser("title", help="render an animated intro/outro title card")
    sp.add_argument("--text", required=True); sp.add_argument("--sub", default="")
    sp.add_argument("-o", "--out", required=True); sp.add_argument("--seconds", type=float, default=6.0)
    sp.add_argument("--style", default="horror", choices=["horror", "clean", "glitch", "warm"])
    sp.add_argument("--size", default="1920x1080"); sp.add_argument("--fps", type=int, default=60)
    sp.add_argument("--letterbox", type=float, default=0.07)
    sp.add_argument("--flicker", default="auto", choices=["auto", "on", "off"])
    sp.add_argument("--logo", help="path to a logo / channel-avatar image to show on the card")
    sp.add_argument("--cta", help="call-to-action pill, e.g. 'SUBSCRIBE & LIKE'")
    sp.add_argument("--silent", action="store_true", help="no rumble bed"); enc(sp)
    sp.set_defaults(func=cmd_title)

    sp = sub.add_parser("transcribe", help="on-device speech-to-text + spoken edit-word detection")
    sp.add_argument("video"); sp.add_argument("-o", "--out", help="output basename (.srt/.txt/.json)")
    sp.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large-v3"])
    sp.add_argument("--lang", help="language code (e.g. en); auto-detected if omitted")
    sp.add_argument("--find", help="comma-separated trigger phrases (default: the edit/cut-this-out set)")
    sp.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("voice", help="voice-changer / audio effects (video copied, audio only)")
    sp.add_argument("video")
    sp.add_argument("--effect", required=True, choices=list(VOICES) + ["radio", "robot", "denoise", "clean"])
    sp.add_argument("--volume", type=float, default=1.0)
    sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_voice)

    sp = sub.add_parser("scenes", help="detect scene-change cut points (smart alternative to dumping frames)")
    sp.add_argument("video"); sp.add_argument("--threshold", type=float, default=0.3)
    sp.set_defaults(func=cmd_scenes)

    sp = sub.add_parser("preview", help="fast low-res proxy so the user can quickly SEE the current state")
    sp.add_argument("video"); sp.add_argument("-o", "--out")
    sp.add_argument("--height", type=int, default=480); sp.add_argument("--crf", type=int, default=30)
    sp.set_defaults(func=cmd_preview)

    sp = sub.add_parser("music", help="mix a background music track under the video (optional ducking)")
    sp.add_argument("video"); sp.add_argument("--track", required=True, help="music/audio file")
    sp.add_argument("--volume", type=float, default=0.22); sp.add_argument("--fade", type=float, default=2.0)
    sp.add_argument("--duck", action="store_true", help="dip the music under speech (sidechain)")
    sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_music)

    sp = sub.add_parser("profile", aliases=["channel"],
                        help="grab a PUBLIC avatar + name (YouTube/Steam/Roblox/any og:image) — no API key")
    sp.add_argument("target", help="profile URL, @handle, or username")
    sp.add_argument("--platform", default="auto",
                    choices=["auto", "youtube", "steam", "roblox", "generic"])
    sp.add_argument("-o", "--out", help="output dir for the avatar (default: channel_assets)")
    sp.set_defaults(func=cmd_profile)

    sp = sub.add_parser("thumbnail", help="make a 1280x720 YouTube thumbnail (frame + big text + avatar)")
    sp.add_argument("video"); sp.add_argument("--text", required=True)
    sp.add_argument("--sub"); sp.add_argument("--at", type=float, help="frame time (default: middle)")
    sp.add_argument("--logo", help="avatar/logo image (e.g. from `profile`)")
    sp.add_argument("--accent", default="red", help="accent color: name or hex, e.g. e6283c")
    sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_thumbnail)

    sp = sub.add_parser("inspect", help="WATCH-FIRST: spec + contact sheet + scenes + review checklist")
    sp.add_argument("video"); sp.add_argument("--count", type=int, default=30)
    sp.add_argument("-o", "--out", help="contact sheet path")
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser("short", help="convert to a 9:16 YouTube Short/Reel (blurred pad or crop) + optional metadata")
    sp.add_argument("video"); sp.add_argument("--start", type=float, default=0.0)
    sp.add_argument("--end", type=float)
    sp.add_argument("--mode", default="pad", choices=["pad", "crop"])
    sp.add_argument("--max", type=float, default=60.0, help="max length in seconds (Shorts cap)")
    sp.add_argument("--title"); sp.add_argument("--tags"); sp.add_argument("--desc")
    sp.add_argument("-o", "--out"); enc(sp)
    sp.set_defaults(func=cmd_short)

    sp = sub.add_parser("split", help="split a long video into chunks (for feeding to an AI) + a manifest")
    sp.add_argument("video")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--minutes", type=float, default=5.0, help="chunk length in minutes (default 5)")
    g.add_argument("--parts", type=int, help="split into N equal parts")
    sp.add_argument("-o", "--out", help="output dir (default: <video>_chunks)")
    sp.set_defaults(func=cmd_split)

    sp = sub.add_parser("captions", help="burn captions into the video from an .srt (auto-transcribes if needed)")
    sp.add_argument("video"); sp.add_argument("--srt", help="subtitle file (default: alongside the video, else transcribe)")
    sp.add_argument("--style", default="clean", choices=list(CAPTION_STYLES))
    sp.add_argument("--size", type=int, help="font size override")
    sp.add_argument("--color", help="text color hex, e.g. FFD400")
    sp.add_argument("--margin", type=int, help="distance from the edge in px")
    sp.add_argument("--model", default="base", help="Whisper model if transcribing")
    sp.add_argument("--lang"); sp.add_argument("--force", action="store_true", help="re-transcribe even if an .srt exists")
    sp.add_argument("-o", "--out"); enc(sp)
    sp.set_defaults(func=cmd_captions)

    sp = sub.add_parser("smooth", help="motion-interpolate to a higher fps for buttery motion (slow)")
    sp.add_argument("video"); sp.add_argument("--fps", type=int, default=60)
    sp.add_argument("--height", type=int, help="also rescale, e.g. 1080")
    sp.add_argument("-o", "--out"); enc(sp)
    sp.set_defaults(func=cmd_smooth)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
