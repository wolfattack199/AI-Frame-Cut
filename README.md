# frameforge

**Give Claude eyes for video, and fast hands to edit it.**

`frameforge` is a tiny, local, no-API-key video toolkit designed for AI coding
agents (Claude Code, and anything that can run a shell). It solves two problems an
agent has with video:

1. **Seeing it.** LLMs can't watch an MP4. `frameforge contact` turns a whole video
   into a single labeled contact-sheet image the agent can look at in one glance —
   or `frameforge frames` dumps frames at *any* frame rate (10 / 15 / 30 fps, or N
   evenly spaced).
2. **Editing it, fast.** One-line commands for the things you actually want: a
   cinematic color grade, animated intro/outro title cards, instant keyframe trims,
   highlight cuts, concatenation, speed changes, resize, and gif export — powered by
   ffmpeg, no cloud, no transcription, no waiting.

It's built to be **added as a skill**: drop it in your agent's skills folder, and you
can just say *"make this gameplay clip cinematic and give it an intro"* — the agent
looks at it and does it, even for 8-minute videos.

## Requirements

- **ffmpeg** and **ffprobe** on your PATH (or in `~/.local/bin`)
- **Python 3.9+** with [uv](https://docs.astral.sh/uv/) (or pip)

## Install

```bash
git clone https://github.com/YOUR_USERNAME/frameforge ~/.claude/skills/frameforge
cd ~/.claude/skills/frameforge
uv sync                       # or: pip install -e .
frameforge doctor             # confirm ffmpeg is found
```

That places it in Claude Code's skills directory. For other agents, put it in their
skills folder (`~/.codex/skills/`, etc.) or point their config at `SKILL.md`.

Don't have ffmpeg? See [`install.md`](install.md) — it covers a no-admin static build
on Windows plus macOS/Linux.

## Quick start

```bash
frameforge probe   clip.mp4
frameforge contact clip.mp4                         # -> clip_contact.png (look at it)
frameforge grade   clip.mp4 --look cinematic --height 1080 --letterbox 0.07
frameforge title   --text "LIGHTS OUT" --sub "APRIL 10" --style horror -o intro.mp4
frameforge concat  final.mp4 intro.mp4 clip_cinematic.mp4
```

See [`SKILL.md`](SKILL.md) for the full command reference and agent recipes.

## Commands

`probe` · `contact` · `frames` · `thumb` · `grade` · `title` · `trim` · `cut` ·
`concat` · `speed` · `resize` · `gif` · `audio` · `doctor`

Grade looks: `cinematic`, `noir`, `warm`, `cold`, `vhs`, `clean`.
Title styles: `horror`, `clean`, `glitch`, `warm`.

## License

MIT — see [LICENSE](LICENSE). Built to be forked, renamed, and extended.
