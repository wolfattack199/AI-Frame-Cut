"""AI Frame Cut â€” give Claude & ChatGPT eyes, ears, and fast hands for video.

Local and dependency-light: SEE a video (contact sheets, scene detection, frames at
any fps), HEAR it (on-device Whisper transcription + spoken edit-word detection), and
EDIT it fast â€” grade, animated titles (with optional channel avatar + Subscribe/Like
CTA), background music with ducking, trim, cut, concat, speed, resize, gif, voice/audio
effects, and quick previews â€” all over ffmpeg + Pillow + faster-whisper. Can also grab a
public YouTube channel's avatar + name (no API key) for branding.

No cloud services, no API keys (the only network use is the public YouTube channel fetch
and the one-time Whisper model download). Everything runs on the user's own device.
"""

__version__ = "0.7.0"
