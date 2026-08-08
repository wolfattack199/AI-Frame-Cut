---
name: ai-frame-cut
description: Fast, local, no-API-key video editing for gameplay, screen recordings, talking-heads, and montages. SEE any video as a labeled contact sheet or frames at any frame rate, HEAR it via on-device Whisper transcription (with spoken "edit this out" detection), and EDIT it with one-line commands — cinematic color grade, animated intro/outro title cards (optionally with a channel avatar + Subscribe/Like call-to-action), background music with auto-ducking, keyframe-instant trims, highlight cuts, concat, speed, resize, gif, voice/audio effects, YouTube thumbnails, vertical Shorts, long-video splitting, and quick previews so the user can watch progress. It inspects the video first (contact sheet + review checklist) before asking how to edit, and can grab a PUBLIC YouTube / Steam / Roblox profile avatar + name (no API key). Optional NVIDIA --gpu encoding. Use whenever the user wants to look at a video and make it better quickly, even 8-minute clips.
---

# AI Frame Cut

**Give Claude & ChatGPT eyes, ears, and fast hands for video.** A thin ffmpeg +
Whisper wrapper built for an AI workflow: look first, then edit with tiny commands.
Local, no API keys, no cloud.

## Start here: work WITH the user (do this EVERY time)

The user often can't see what you're doing, and may not even know what the video needs.
So **watch it first, then ask** — never edit blind, never disappear:

1. **WATCH the video FIRST.** Run `inspect VIDEO` — it gives the spec, a contact sheet to
   Read, a scene count, and a review checklist. **Actually LOOK at the contact sheet.** If
   there's speech, also `transcribe`.
2. **Report what you saw, and offer choices — don't start editing.** Tell the user what's in
   the video and proactively **flag anything to remove for privacy** (passwords / login
   screens, real names, emails, phone numbers, home address, OBS or streamer dashboards,
   other people, private tabs, DMs) plus obvious fixes (dead air, menus at the start, could
   use captions). Then **ask how they want it edited** — e.g. *"remove the password, cut the
   boring parts, add a Subscribe outro?"* Let them pick.
3. **Capture their vision** if they haven't said: platform (YouTube / Shorts → aspect + length),
   vibe, intro/outro, a **channel / Steam / Roblox** handle to brand with, music, CTAs.
4. **Show a short plan**, then edit **step-by-step and let them WATCH** — after each meaningful
   step run `preview` (or `contact`) on the output and **show it**, saying what you did. That
   is how they "watch it edit." Long renders → run in the background and `preview` when done.
5. **Iterate** on each preview.

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
| `inspect VIDEO` | **WATCH-FIRST bundle** — spec + contact sheet + scene count + a privacy/edit review checklist (run this before asking how to edit) |
| `probe VIDEO [--json]` | duration, resolution, fps, codecs, audio, size |
| `contact VIDEO [--count 30 \| --every 16] [--cols 6] [--tile-width 320] [--start --end]` | **labeled contact sheet** of the whole video → a PNG you Read to see it |
| `scenes VIDEO [--threshold 0.3]` | detect scene-change timecodes (smart cut points, not thousands of frames) |
| `frames VIDEO [--fps 10 \| --count 24] [--width] [--start --end]` | dump frames at **any** frame rate or N evenly spaced |
| `thumb VIDEO --at 42 [--width]` | one frame at a timestamp |
| `transcribe VIDEO [--model base] [--lang en] [--find "phrase,..."] [--device cpu\|cuda]` | on-device Whisper → `.srt/.txt/.json` + spoken **edit-word** marks |
| `grade VIDEO [--look cinematic] [--height 1080] [--letterbox 0.07] [--fps] [--gpu]` | one-word color grade |
| `title --text "..." [--sub "..."] [--cta "SUBSCRIBE & LIKE"] [--logo avatar.png] [--seconds 6] [--style horror] [--size 1920x1080] [--letterbox 0.07] [--silent] -o OUT.mp4` | animated intro/outro card — add `--logo` for a circular channel avatar and `--cta` for a Subscribe/Like pill |
| `trim VIDEO --start 25 [--end 60] [--reencode]` | cut one span. Default **keyframe-instant**; `--reencode` for frame-accuracy |
| `cut VIDEO --keep 5-12,40-55` | keep + join highlight segments (frame-accurate) |
| `concat OUT CLIP1 CLIP2 ...` | join clips (stream-copy if compatible, else re-encode) |
| `voice VIDEO --effect deep [--volume 1.0]` | voice-changer / audio effects (video copied, audio only — fast) |
| `music VIDEO --track song.mp3 [--duck] [--volume 0.22] [--fade 2]` | mix background music under the video; `--duck` dips it under speech |
| `preview VIDEO [--height 480]` | **fast low-res proxy** — make one after each step and SHOW the user so they watch progress |
| `profile URL_or_@handle_or_username [--platform auto]` (alias `channel`) | grab a PUBLIC avatar + name from **YouTube / Steam / Roblox** (or any og:image page) — no API key → `channel_assets/channel_avatar.png` |
| `thumbnail VIDEO --text "..." [--sub "..."] [--at T] [--logo avatar.png] [--accent red]` | a **1280×720 YouTube thumbnail** from a frame + big outlined text + avatar badge |
| `speed VIDEO --factor 2.0 [--mute]` | speed up / slow down, pitch-preserved |
| `short VIDEO [--start --end] [--mode pad\|crop] [--max 60] [--title --tags --desc]` | make a 9:16 **YouTube Short/Reel** (`pad` = blurred bg, whole frame kept; `crop` = fill) + a metadata sidecar |
| `split VIDEO [--minutes 5 \| --parts N]` | slice a **long video** into chunks + a `chunks.txt` manifest, to process piece by piece |
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

**"Edit this for YouTube — branded intro/outro + music":**
```
aiframecut channel @theirhandle                       # -> channel_assets/channel_avatar.png + name
aiframecut title --text "THEIR CHANNEL" --logo channel_assets/channel_avatar.png --style clean --seconds 5 -o intro.mp4
# ...build the graded body (see the cinematic recipe above)...
aiframecut title --text "THANKS FOR WATCHING" --cta "SUBSCRIBE & LIKE" --logo channel_assets/channel_avatar.png --style clean --flicker off -o outro.mp4
aiframecut concat joined.mp4 intro.mp4 body.mp4 outro.mp4
aiframecut music joined.mp4 --track music.mp3 --duck -o final.mp4    # music under everything, ducked under speech
aiframecut preview final.mp4 -o final_preview.mp4                    # then SHOW this to the user
```

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
- **`profile`/`channel` is the only online feature.** It reads PUBLIC pages/APIs (YouTube og:image, the Steam profile page, the Roblox public API) — no login, no API key. Ask the user for their profile URL / @handle / username and only fetch what they give you.
- **Music needs a track the user provides** (a file path). The tool mixes / ducks / fades it — it doesn't source or generate music itself.
- **Long videos → `split` first.** For an hour-long stream, `split` it into chunks, then `inspect` / `transcribe` and pick highlights from each chunk before assembling. Don't try to process it all in one pass.
- **Shorts:** pick a ≤60s moment, then `short` it (`--mode pad` keeps gameplay uncropped). Then propose a **title + tags + description** to the user, and save them with `--title/--tags/--desc`.
