---
name: frameforge
description: Fast, local video editing for gameplay, screen recordings, talking-heads, montages — no API keys, no transcription, no waiting on cloud renders. SEE any video instantly as a labeled contact sheet or as frames at any frame rate (10/15/30fps...), then EDIT with one-line commands — cinematic color grade, animated intro/outro title cards, keyframe-instant trims, highlight cuts, concat, speed, resize, gif, audio. Use whenever the user wants to look at a video and make it better quickly, even 8-minute clips.
---

# frameforge

**Give Claude eyes for video, and fast hands to edit it.** A thin ffmpeg wrapper
built for *your* workflow: look first, then edit with tiny commands. No API keys.

## The golden loop

1. **SEE it** — `contact` gives you one labeled image of the whole video. `probe`
   gives you the specs. Never edit a video you haven't looked at.
2. **PLAN it** — from the contact sheet, decide what to cut, where the good parts
   are, what look fits. Confirm anything destructive with the user.
3. **EDIT it** — chain single commands: `grade`, `title`, `trim`, `cut`, `concat`.
4. **VERIFY it** — `thumb` / `contact` the *output* before declaring done.

## How to run it

From this skill directory (deps live in its own venv):

```
uv run --directory <path-to-this-skill> frameforge <command> [args]
```

`<path-to-this-skill>` is wherever this folder lives (e.g. `~/.claude/skills/frameforge`).
Run `frameforge doctor` first on a new machine to confirm ffmpeg is found.

## Command reference

| Command | What it does |
|---|---|
| `probe VIDEO [--json]` | duration, resolution, fps, codecs, audio, size |
| `contact VIDEO [--count 30 \| --every 16] [--cols 6] [--tile-width 320] [--start --end]` | **labeled contact sheet** of the whole video → a PNG you Read to see it |
| `frames VIDEO [--fps 10 \| --count 24] [--width] [--start --end] [-o DIR]` | dump frames at **any** frame rate or N evenly spaced |
| `thumb VIDEO --at 42 [--width]` | one frame at a timestamp |
| `grade VIDEO [--look cinematic] [--height 1080] [--letterbox 0.07] [--fps]` | one-word color grade (see looks below) |
| `title --text "LIGHTS OUT" [--sub "APRIL 10"] [--seconds 6] [--style horror] [--size 1920x1080] [--letterbox 0.07] [--silent] -o OUT.mp4` | animated intro/outro card |
| `trim VIDEO --start 25 [--end 60] [--reencode]` | cut one span. Default is **keyframe-instant** (copy). `--reencode` for frame-accuracy |
| `cut VIDEO --keep 5-12,40-55` | keep + join highlight segments (frame-accurate, one pass) |
| `concat OUT CLIP1 CLIP2 ...` | join clips (stream-copy if compatible, else auto re-encode) |
| `speed VIDEO --factor 2.0 [--mute]` | speed up / slow down, pitch-preserved audio |
| `resize VIDEO --height 1080` | downscale (keeps audio) |
| `gif VIDEO --start 10 --end 14 [--fps 15] [--width 480]` | palette-optimized gif |
| `audio VIDEO` | extract audio to mp3 |
| `doctor` | check ffmpeg / pillow / list looks & styles |

**Looks** (for `grade --look`): `cinematic` (moody, cool shadows / warm highlights,
vignette, light grain), `noir` (b&w, high contrast), `warm`, `cold`, `vhs`, `clean`.
**Title styles**: `horror` (red glow + flicker), `clean`, `glitch` (cyan), `warm`.

Every edit command takes `-o/--out` (a sensible default is chosen if omitted) and
`--crf` / `--preset` for quality/speed.

## Recipes

**"Make my gameplay clip cinematic with an intro"** (what most requests want):
```
frameforge contact raw.mp4                 # → Read raw_contact.png, find where real content starts
frameforge trim raw.mp4 --start 25 -o body.mp4          # drop menus/dead air (instant)
frameforge grade body.mp4 --look cinematic --height 1080 --letterbox 0.07 -o graded.mp4
frameforge title --text "LIGHTS OUT" --sub "APRIL 10" --seconds 6 --style horror -o intro.mp4
frameforge title --text "LIGHTS OUT" --seconds 3.5 --style horror --flicker off -o outro.mp4
frameforge concat final.mp4 intro.mp4 graded.mp4 outro.mp4
frameforge thumb final.mp4 --at 7        # verify it opens on real content
```

**"Cut this into a 30-second highlight":** `contact` to find the beats → `cut --keep a-b,c-d,...` → `grade`.

**"Turn my 8-min 4K60 into something shareable":** `grade in.mp4 --look cinematic --height 1080`
(downscaling is the single biggest speed + filesize win). For very long renders,
launch them in the background and verify with `contact` when done.

## Rules that keep output correct

- **Look before you cut.** Always `contact`/`probe` first. Screen recordings often
  start on the desktop / a launcher / menus — trim that, and never leave a user's
  private dashboard (OBS, tabs, credentials) in the output.
- **Match params before concat.** `concat` stream-copies only when width/height/fps/
  codecs match; otherwise it re-encodes to the first clip's spec. Make title cards at
  the same size/fps as the body (default 1920x1080@60) for instant joins.
- **Keyframe trims are approximate at the head/tail.** For a precise cut use `--reencode`
  (or `cut`, which is always frame-accurate).
- **Downscale for delivery.** 1080p is the sweet spot; only keep 4K if asked.
- **Verify before you present.** Read a `thumb`/`contact` of the final render.
