# Changelog

All notable changes to **AI Frame Cut**. Newest release on top.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/); this project uses
[semantic versioning](https://semver.org/).

## [0.5.0] — 2026-08-08

### Added
- **`short`** — convert a clip to a 9:16 **YouTube Short / Reel** (1080×1920). `--mode pad`
  keeps your whole frame visible over a blurred background (great for gameplay); `--mode crop`
  fills the frame. Caps length with `--max` (default 60s). Optional `--title`/`--tags`/`--desc`
  write a ready-to-paste metadata file next to the Short.
- **`split`** — slice a long video (e.g. an hour-long stream) into chunks with `--minutes` or
  `--parts`, plus a `chunks.txt` manifest — so an AI can work through a long video piece by piece.
- **`CHANGELOG.md`** (this file).

## [0.4.0] — 2026-08-07

### Added
- **`thumbnail`** — a 1280×720 YouTube thumbnail from a frame + big outlined headline + accent
  bar + circular avatar badge.
- **`profile`** (alias **`channel`**) — grab a PUBLIC avatar + name from **YouTube, Steam, or
  Roblox** (or any og:image page), no API key. Steam reads the profile avatar element; Roblox
  uses the public users + thumbnails API.
- **`inspect`** — a WATCH-FIRST bundle: spec + contact sheet + scene count + a privacy/edit
  review checklist.

### Changed
- Workflow doctrine (SKILL.md): **watch the video first, flag anything private to remove, then
  ask the user how to edit** — before touching anything.

## [0.3.0] — 2026-08-07

### Added
- **`preview`** — a fast low-res proxy so the user can watch progress after each step.
- **`music`** — mix a background track under the video, with optional `--duck` (music dips
  under speech) and fades.
- **`channel`** — grab a PUBLIC YouTube channel's avatar + name (no API key).
- **`title --logo` / `--cta`** — put a circular channel avatar and a Subscribe/Like pill on
  intro/outro cards.

### Changed
- Workflow doctrine: interview the user first, then edit step-by-step showing previews.

## [0.2.0] — 2026-08-07

### Added
- On-device **`transcribe`** (faster-whisper, no API key) → `.srt/.txt/.json`, with spoken
  **"edit this out"** detection.
- **`voice`** — voice-changer / audio effects (deep, high, robot, radio, denoise…).
- **`scenes`** — scene-change cut-point detection.
- **`--gpu`** — optional NVIDIA NVENC hardware encoding on encode commands.

### Changed
- Renamed the project from **frameforge** to **AI Frame Cut** (package `aiframecut`).
- Pinned Python to 3.12 for the Whisper wheels (uv fetches it automatically).

## [0.1.0] — 2026-08-07

### Added
- Initial release: `probe`, `contact` (labeled contact sheets), `frames`, `thumb`, `grade`
  (cinematic/noir/warm/cold/vhs/clean), `title` (animated intro/outro cards), `trim`, `cut`,
  `concat`, `speed`, `resize`, `gif`, `audio`, `doctor`. Local, ffmpeg + Pillow, no API keys.
