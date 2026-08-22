# AI Frame Cut

**Give Claude & ChatGPT eyes, ears, and fast hands for video.**

AI Frame Cut is a small, **local, no-API-key** video toolkit designed for AI agents
(Claude Code, ChatGPT/Codex, and anything that can run a terminal). Point an agent at
this repo, tell it *"use this,"* and it can edit whole videos on your device.

It solves four problems an AI has with video:

1. **Seeing it.** LLMs can't watch an MP4. `contact` turns a whole video into one
   labeled contact-sheet image the agent reads in a glance; `scenes` finds cut points;
   `frames` dumps frames at *any* rate (10/15/30 fps).
2. **Hearing it.** `transcribe` runs **Whisper on your own device** (no API key) into
   `.srt/.txt/.json` transcripts, flags spoken **"edit this out"** moments, and feeds
   `captions` to burn subtitles straight into the video.
3. **Editing it, fast.** One-line commands: cinematic color grade, animated intro/outro
   titles (optionally with your **channel avatar + a Subscribe/Like** pill), **background
   music** with auto-ducking, instant keyframe trims, highlight cuts, concat, vertical
   **Shorts**, speed, resize, gif, and voice/audio effects. Optional **NVIDIA `--gpu`**
   encoding and a **`--quality max`** mode.
4. **Working with you.** It **watches the video first** (`inspect`), flags anything private to
   remove (passwords, real names, an OBS dashboard on screen...), then **asks how you want it
   edited** — and works step-by-step, handing you a fast **`preview`** after each step so you
   watch it take shape. It can grab a **public YouTube / Steam / Roblox** avatar + name (no API
   key) to brand your intro/outro, and build a **YouTube thumbnail**.

So you can say *"edit this gameplay for YouTube — clean intro with my channel logo, some
music, cut the boring parts, and a Subscribe outro"* — and the agent asks what you're
picturing, then looks, listens, and builds it, showing you previews along the way.

> **Honest speed note:** re-encoding a long/4K video takes *minutes, not seconds* — that's
> the CPU compressing every frame. What's instant: seeing it, and keyframe copy-cuts.
> Downscaling to 1080p, re-encoding only what changes, and `--gpu` are the real speedups.

## Requirements

- **ffmpeg** + **ffprobe** on PATH (or in `~/.local/bin`) — see [`install.md`](install.md)
- **Python** with [uv](https://docs.astral.sh/uv/) — the project pins 3.12 (for the Whisper
  wheels); uv fetches it automatically. `faster-whisper` and `pillow` install on `uv sync`.

## Install

```bash
git clone https://github.com/YOUR_USERNAME/AI-Frame-Cut ~/.claude/skills/ai-frame-cut
cd ~/.claude/skills/ai-frame-cut
uv sync
aiframecut doctor        # confirms ffmpeg, Whisper, and GPU availability
```

For other agents, put it in their skills folder (`~/.codex/skills/`, ...) or point their
config at `SKILL.md`. Once published, agents can also add it with the `skills` CLI:
`npx skills add YOUR_USERNAME/AI-Frame-Cut`.

## Quick start

```bash
aiframecut inspect    clip.mp4                       # watch it first: specs + contact sheet
aiframecut transcribe clip.mp4                       # -> clip.srt/.txt/.json + edit-marks
aiframecut captions   clip.mp4 --style clean         # burn the subtitles in
aiframecut grade      clip.mp4 --look cinematic --height 1080 --letterbox 0.07
aiframecut title      --text "LIGHTS OUT" --sub "APRIL 10" --style horror -o intro.mp4
aiframecut concat     final.mp4 intro.mp4 clip_cinematic.mp4
```

See [`SKILL.md`](SKILL.md) for the full command reference and agent recipes.

## Commands

`inspect` · `probe` · `contact` · `scenes` · `frames` · `thumb` · `transcribe` · `captions` ·
`grade` · `title` · `thumbnail` · `trim` · `cut` · `concat` · `short` · `split` · `smooth` ·
`voice` · `music` · `preview` · `profile` (YouTube/Steam/Roblox) · `speed` · `resize` ·
`gif` · `audio` · `doctor`

Encode commands support **`--quality max`** (native-res near-lossless), **`--keyint`** (dense
keyframes), and **`--gpu`** (full NVIDIA decode+encode).

See [`CHANGELOG.md`](CHANGELOG.md) for what's new in each release.

- **Grade looks:** `cinematic`, `noir`, `warm`, `cold`, `vhs`, `clean`
- **Title styles:** `horror`, `clean`, `glitch`, `warm`
- **Caption styles:** `clean`, `bold`, `yellow`, `box`, `top`
- **Voice effects:** `deep`, `deeper`, `high`, `chipmunk`, `radio`, `robot`, `denoise`, `clean`

## License

MIT — see [LICENSE](LICENSE). Built to be forked, renamed, and extended.
