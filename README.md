# AI Frame Cut

**Give Claude & ChatGPT eyes, ears, and fast hands for video.**

AI Frame Cut is a small, **local, no-API-key** video toolkit designed for AI agents
(Claude Code, ChatGPT/Codex, and anything that can run a terminal). Point an agent at
this repo, tell it *"use this,"* and it can edit whole videos on your device.

It solves three problems an AI has with video:

1. **Seeing it.** LLMs can't watch an MP4. `contact` turns a whole video into one
   labeled contact-sheet image the agent reads in a glance; `scenes` finds cut points;
   `frames` dumps frames at *any* rate (10/15/30 fps).
2. **Hearing it.** `transcribe` runs **Whisper on your own device** (no API key) →
   `.srt/.txt/.json` transcripts, and flags spoken **"edit this out"** moments so the
   agent knows where to cut.
3. **Editing it, fast.** One-line commands: cinematic color grade, animated intro/outro
   titles, instant keyframe trims, highlight cuts, concat, speed, resize, gif, and
   voice/audio effects. Optional **NVIDIA `--gpu`** encoding.

So you can say *"make this gameplay clip cinematic, give it an intro, and cut the boring
parts I flagged"* — and the agent looks, listens, and does it, even on 8-minute videos.

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

For other agents, put it in their skills folder (`~/.codex/skills/`, …) or point their
config at `SKILL.md`. Once published, agents can also add it with the `skills` CLI:
`npx skills add YOUR_USERNAME/AI-Frame-Cut`.

## Quick start

```bash
aiframecut contact    clip.mp4                       # -> clip_contact.png (look at it)
aiframecut transcribe clip.mp4                       # -> clip.srt/.txt/.json + edit-marks
aiframecut grade      clip.mp4 --look cinematic --height 1080 --letterbox 0.07
aiframecut title      --text "LIGHTS OUT" --sub "APRIL 10" --style horror -o intro.mp4
aiframecut concat     final.mp4 intro.mp4 clip_cinematic.mp4
```

See [`SKILL.md`](SKILL.md) for the full command reference and agent recipes.

## Commands

`probe` · `contact` · `scenes` · `frames` · `thumb` · `transcribe` · `grade` · `title` ·
`trim` · `cut` · `concat` · `voice` · `speed` · `resize` · `gif` · `audio` · `doctor`

- **Grade looks:** `cinematic`, `noir`, `warm`, `cold`, `vhs`, `clean`
- **Title styles:** `horror`, `clean`, `glitch`, `warm`
- **Voice effects:** `deep`, `deeper`, `high`, `chipmunk`, `radio`, `robot`, `denoise`, `clean`

## License

MIT — see [LICENSE](LICENSE). Built to be forked, renamed, and extended.
