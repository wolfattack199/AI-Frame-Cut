---
name: ai-frame-cut
description: Fast, local, no-API-key video editing for gameplay, screen recordings, talking-heads, and montages. SEE any video instantly as a labeled contact sheet or frames at any frame rate, HEAR it via on-device Whisper transcription (with spoken "edit this out" trigger detection), and EDIT it with one-line commands — cinematic color grade, animated intro/outro title cards, keyframe-instant trims, highlight cuts, concat, speed, resize, gif, and voice/audio effects. Optional NVIDIA --gpu encoding. Use whenever the user wants to look at a video and make it better quickly, even 8-minute clips.
---

# AI Frame Cut

**Give Claude & ChatGPT eyes, ears, and fast hands for video.** A thin ffmpeg +
Whisper wrapper built for an AI workflow: look first, then edit with tiny commands.
Local, no API keys, no cloud.

## The golden loop

1. **SEE it** — `contact` gives you one labeled image of the whole video; `scenes`
   finds cut points; `probe` gives specs. Never edit a video you haven't looked at.
2. **HEAR it** (when there's speech) — `transcribe` writes an SRT/JSON transcript and
   flags any spoken "edit this out" moments for you to cut.
3. **PLAN it** — decide what to cut, where the good parts are, what look fits. Confirm
   anything destructive with the user.
4. **EDIT it** — chain single commands: `grade`, `title`, `trim`, `cut`, `concat`, `voice`.
5. **VERIFY it** — `thumb` / `contact` the *output* before declaring done.

## How to run it

From this skill directory (deps live in its own venv):

```
uv run --directory <path-to-this-skill> aiframecut <command> [args]
```

`<path-to-this-skill>` is wherever this folder lives (e.g. `~/.claude/skills/ai-frame-cut`).
Run `aiframecut doctor` first on a new machine — it confirms ffmpeg, Whisper, and
whether NVIDIA `--gpu` encoding is available.

## Command reference

| Command | What it does |
|---|---|
| `probe VIDEO [--json]` | duration, resolution, fps, codecs, audio, size |
| `contact VIDEO [--count 30 \| --every 16] [--cols 6] [--tile-width 320] [--start --end]` | **labeled contact sheet** of the whole video → a PNG you Read to see it |
| `scenes VIDEO [--threshold 0.3]` | detect scene-change timecodes (smart cut points, not thousands of frames) |
| `frames VIDEO [--fps 10 \| --count 24] [--width] [--start --end]` | dump frames at **any** frame rate or N evenly spaced |
| `thumb VIDEO --at 42 [--width]` | one frame at a timestamp |
| `transcribe VIDEO [--model base] [--lang en] [--find "phrase,..."] [--device cpu\|cuda]` | on-device Whisper → `.srt/.txt/.json` + spoken **edit-word** marks |
| `grade VIDEO [--look cinematic] [--height 1080] [--letterbox 0.07] [--fps] [--gpu]` | one-word color grade |
| `title --text "LIGHTS OUT" [--sub "..."] [--seconds 6] [--style horror] [--size 1920x1080] [--letterbox 0.07] [--silent] -o OUT.mp4` | animated intro/outro card |
| `trim VIDEO --start 25 [--end 60] [--reencode]` | cut one span. Default **keyframe-instant**; `--reencode` for frame-accuracy |
| `cut VIDEO --keep 5-12,40-55` | keep + join highlight segments (frame-accurate) |
| `concat OUT CLIP1 CLIP2 ...` | join clips (stream-copy if compatible, else re-encode) |
| `voice VIDEO --effect deep [--volume 1.0]` | voice-changer / audio effects (video copied, audio only — fast) |
| `speed VIDEO --factor 2.0 [--mute]` | speed up / slow down, pitch-preserved |
| `resize VIDEO --height 1080` / `gif VIDEO --start --end` / `audio VIDEO` | rescale / gif / extract mp3 |
| `doctor` | check ffmpeg, Whisper, GPU, and list looks/styles/voices |

**Looks** (`grade --look`): `cinematic`, `noir`, `warm`, `cold`, `vhs`, `clean`.
**Title styles**: `horror`, `clean`, `glitch`, `warm`.
**Voice effects**: `deep`, `deeper`, `high`, `chipmunk`, `radio`, `robot`, `denoise`, `clean`.

Encode commands take `-o/--out`, `--crf`/`--preset`, and `--gpu` (NVIDIA NVENC, if `doctor` shows it).

## Recipes

**"Make my gameplay clip cinematic with an intro":**
```
aiframecut contact raw.mp4                  # Read raw_contact.png; find where real content starts
aiframecut trim raw.mp4 --start 25 -o body.mp4                       # drop menus/dead air (instant)
aiframecut grade body.mp4 --look cinematic --height 1080 --letterbox 0.07 -o graded.mp4
aiframecut title --text "LIGHTS OUT" --sub "APRIL 10" --style horror -o intro.mp4
aiframecut concat final.mp4 intro.mp4 graded.mp4
aiframecut thumb final.mp4 --at 7           # verify it opens on real content
```

**"Cut out the parts where I said to edit them out":**
```
aiframecut transcribe raw.mp4               # reports edit-marks with suggested cut windows
# then keep everything EXCEPT those windows with `cut --keep ...` or several `trim`s
```

**"Cut this into a highlight":** `contact`/`scenes` to find beats → `cut --keep a-b,c-d,...` → `grade`.

**"Turn my 8-min 4K60 into something shareable":** `grade in.mp4 --look cinematic --height 1080`
(downscaling is the biggest speed + filesize win; add `--gpu` if available). Launch long
renders in the background and verify with `contact` when done.

## Rules that keep output correct

- **Look before you cut.** Always `contact`/`probe` first. Screen recordings often start on
  the desktop / a launcher / menus — trim that, and **never leave a user's private dashboard
  (OBS, tabs, credentials) in the output.**
- **Speed is physics.** Re-encoding a long/4K video takes minutes, not seconds. What's instant:
  seeing it, transcribing (minutes), and keyframe copy-cuts. Downscale, only re-encode what
  changes, and use `--gpu` to go faster. Don't promise "seconds" for a full grade.
- **Match params before concat.** `concat` stream-copies only when width/height/fps/codecs match;
  otherwise it re-encodes to the first clip's spec. Build title cards at the body's size/fps.
- **Keyframe trims are approximate at the ends.** For a precise cut use `--reencode` or `cut`.
- **Transcription needs speech.** Whisper's voice-activity filter returns 0 segments on pure
  game/ambient audio — that's correct, not a bug.
- **Verify before you present.** Read a `thumb`/`contact` of the final render.
