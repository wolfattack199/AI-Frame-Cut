---
name: frameforge-install
description: First-time setup for frameforge — Python deps via uv, and ffmpeg on PATH (incl. a no-admin static build on Windows). For daily use read SKILL.md.
---

# frameforge install

Three things must be true on the machine:

1. This repo is cloned somewhere stable (ideally the agent's skills dir).
2. Python deps are installed (`pillow`).
3. `ffmpeg` **and** `ffprobe` are on `PATH` (or in `~/.local/bin`).

## 1. Place + install deps

```bash
# Claude Code:
git clone https://github.com/YOUR_USERNAME/frameforge ~/.claude/skills/frameforge
cd ~/.claude/skills/frameforge
uv sync            # or: pip install -e .
```

## 2. ffmpeg

Check first: `frameforge doctor` (or `ffmpeg -version`). If missing:

- **macOS:** `brew install ffmpeg`
- **Debian/Ubuntu:** `sudo apt-get install -y ffmpeg`
- **Arch:** `sudo pacman -S ffmpeg`
- **Windows (no admin):** download a static build and drop it in `~/.local/bin`
  (which frameforge also searches even if it isn't on PATH):

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
frameforge doctor
# then, against any real file:
frameforge probe some_video.mp4
frameforge contact some_video.mp4     # produces some_video_contact.png
```

If `doctor` shows ffmpeg/ffprobe paths and `contact` writes a PNG, you're done.

## Notes

- Pure ffmpeg + Pillow. No API keys, no network calls, nothing sent anywhere.
- Long renders (grading an 8-minute 4K clip) are CPU-bound — launch them in the
  background and verify the output with `frameforge contact` when finished.
- `frameforge --version` and `frameforge <cmd> --help` work for everything.
