---
name: ai-frame-cut-install
description: First-time setup for AI Frame Cut — Python deps via uv (pillow + faster-whisper), and ffmpeg on PATH (incl. a no-admin static build on Windows). For daily use read SKILL.md.
---

# AI Frame Cut install

Three things must be true on the machine:

1. This repo is cloned somewhere stable (ideally the agent's skills dir).
2. Python deps are installed (`pillow`, `faster-whisper`) via `uv sync`.
3. `ffmpeg` **and** `ffprobe` are on `PATH` (or in `~/.local/bin`).

## 1. Place + install deps

```bash
# Claude Code:
git clone https://github.com/YOUR_USERNAME/AI-Frame-Cut ~/.claude/skills/ai-frame-cut
cd ~/.claude/skills/ai-frame-cut
uv sync
```

The project pins **Python 3.12** (via `.python-version`) because the Whisper transcription
library doesn't ship wheels for the very newest Python yet — `uv` downloads 3.12 for you.
First `uv sync` pulls `faster-whisper` + `ctranslate2` (~a few hundred MB, one time).

## 2. ffmpeg

Check first: `aiframecut doctor` (or `ffmpeg -version`). If missing:

- **macOS:** `brew install ffmpeg`
- **Debian/Ubuntu:** `sudo apt-get install -y ffmpeg`
- **Arch:** `sudo pacman -S ffmpeg`
- **Windows (no admin):** download a static build and drop it in `~/.local/bin`
  (which AI Frame Cut also searches even if it isn't on PATH):

  ```powershell
  $dir = "$env:USERPROFILE\.local\bin"; New-Item -ItemType Directory -Force $dir | Out-Null
  $zip = "$env:TEMP\ffmpeg.zip"
  Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
  Expand-Archive $zip "$env:TEMP\ffmpeg_x" -Force
  Get-ChildItem "$env:TEMP\ffmpeg_x" -Recurse -Include ffmpeg.exe,ffprobe.exe |
    ForEach-Object { Copy-Item $_.FullName $dir -Force }
  ```

## 3. Verify end to end

```bash
aiframecut doctor                       # shows ffmpeg, Whisper, and GPU status
aiframecut probe   some_video.mp4
aiframecut contact some_video.mp4       # produces some_video_contact.png
```

If `doctor` shows ffmpeg + `faster-whisper` and `contact` writes a PNG, you're done. The
first `transcribe` run downloads a small Whisper model (cached after).

## Notes

- Local only: ffmpeg + Pillow + on-device Whisper. No API keys; the only network use is the
  one-time Whisper model download from Hugging Face.
- **NVIDIA GPU?** `doctor` will say if `h264_nvenc` is available — pass `--gpu` on encode
  commands (`grade`, `concat`, `cut`, `speed`, `resize`) to speed up encoding.
- Long renders (grading an 8-minute 4K clip) are CPU-bound — launch them in the background
  and verify with `aiframecut contact` when finished.
- `aiframecut --version` and `aiframecut <cmd> --help` work for everything.
