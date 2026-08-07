"""frameforge command-line interface."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from . import __version__
from ._ffmpeg import (FFMPEG, FFPROBE, ffmpeg, probe, fmt_tc, default_out, run, grab_frame)
from .titles import build_contact_sheet, make_title_card

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

VENC = lambda a: ["-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf), "-pix_fmt", "yuv420p"]
AENC = ["-c:a", "aac", "-b:a", "160k"]


def _letterbox_filters(frac: float) -> list[str]:
    return [f"drawbox=y=0:w=iw:h=ih*{frac}:color=black:t=fill",
            f"drawbox=y=ih*(1-{frac}):w=iw:h=ih*{frac}:color=black:t=fill"]


def _print(d):
    print(json.dumps(d, indent=2) if isinstance(d, (dict, list)) else d)


# ------------------------------------------------------------- commands ----
def cmd_doctor(a):
    print(f"frameforge {__version__}")
    print(f"python     {sys.version.split()[0]}")
    print(f"ffmpeg     {FFMPEG or 'NOT FOUND'}")
    print(f"ffprobe    {FFPROBE or 'NOT FOUND'}")
    try:
        import PIL
        print(f"pillow     {PIL.__version__}")
    except Exception:
        print("pillow     NOT INSTALLED")
    if FFMPEG:
        v = run([FFMPEG, "-version"]).stdout.splitlines()[0]
        print(f"           {v}")
    print("looks     ", ", ".join(LOOKS))
    print("styles    ", "horror, clean, glitch, warm")


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
        sys.exit(f"[frameforge] unknown look '{a.look}'. options: {', '.join(LOOKS)}")
    chain = []
    if a.height:
        chain.append(f"scale=-2:{a.height}:flags=lanczos")
    chain.append(look)
    if a.letterbox and a.letterbox > 0:
        chain += _letterbox_filters(a.letterbox)
    out = a.out or default_out(a.video, f"_{a.look}.mp4")
    args = ["-i", str(a.video), "-vf", ",".join(chain), *VENC(a)]
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
            sys.exit(f"[frameforge] bad segment '{part}', expected START-END (e.g. 12-30)")
        a_s, b_s = part.split("-", 1)
        segs.append((float(a_s), float(b_s)))
    if not segs:
        sys.exit("[frameforge] no segments given")
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
    ffmpeg(["-i", str(a.video), "-filter_complex", ";".join(parts), *maps, *VENC(a), out])
    kept = sum(e - s for s, e in segs)
    print(f"kept {n} segment(s) ({kept:.1f}s total) -> {out}")


def cmd_concat(a):
    clips = a.clips
    for c in clips:
        if not Path(c).exists():
            sys.exit(f"[frameforge] clip not found: {c}")
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
    ffmpeg(["-i", str(a.video), "-filter_complex", fc, *maps, *VENC(a), out])
    print(f"speed x{a.factor} -> {out}")


def cmd_resize(a):
    out = a.out or default_out(a.video, f"_{a.height or a.width}.mp4")
    if a.height:
        vf = f"scale=-2:{a.height}:flags=lanczos"
    else:
        vf = f"scale={a.width}:-2:flags=lanczos"
    ffmpeg(["-i", str(a.video), "-vf", vf, *VENC(a), "-c:a", "copy", out])
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
                    audio=not a.silent, crf=a.crf, preset=a.preset)
    print(f"title card '{a.text}' ({a.seconds:g}s, style {a.style}) -> {a.out}")


# --------------------------------------------------------------- parser ----
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="frameforge",
                                description="Give Claude eyes for video, and fast hands to edit it.")
    p.add_argument("--version", action="version", version=f"frameforge {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def enc(sp):  # shared encode flags
        sp.add_argument("--crf", type=int, default=20)
        sp.add_argument("--preset", default="medium")

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
    sp.add_argument("--silent", action="store_true", help="no rumble bed"); enc(sp)
    sp.set_defaults(func=cmd_title)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
