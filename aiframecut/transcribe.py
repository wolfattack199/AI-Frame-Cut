"""On-device speech-to-text (faster-whisper) + spoken edit-word detection. No API key.

Extracts the audio, runs Whisper locally, and writes .srt / .txt / .json transcripts.
It also scans for spoken "cut this out" style phrases and returns them as edit-marks
(with a suggested cut window) so the agent can act on them.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from ._ffmpeg import ffmpeg, default_out

# Spoken phrases that mean "cut this part out" when said into the mic while recording.
DEFAULT_TRIGGERS = [
    "edit this out", "edit that out", "edit this part out", "edit out",
    "cut this out", "cut that out", "cut this part", "cut that part",
    "take this out", "take that out", "remove this part", "delete this",
    "editor cut this", "editor cut that",
]


def _extract_wav(video, wav):
    # Whisper wants 16 kHz mono PCM.
    ffmpeg(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments, path):
    out = []
    for i, s in enumerate(segments, 1):
        out += [str(i), f"{_srt_time(s['start'])} --> {_srt_time(s['end'])}", s["text"], ""]
    Path(path).write_text("\n".join(out), encoding="utf-8")


def find_marks(segments, triggers, pad_before=6.0, pad_after=0.5):
    """Find spoken trigger phrases and suggest a cut window ending just after them."""
    marks = []
    for s in segments:
        low = s["text"].lower()
        for trig in triggers:
            if trig in low:
                marks.append({
                    "trigger": trig,
                    "at": round(s["start"], 2),
                    "said": s["text"].strip(),
                    "suggested_cut": [round(max(0.0, s["start"] - pad_before), 2),
                                      round(s["end"] + pad_after, 2)],
                })
                break
    return marks


def transcribe_file(video, model_size="base", language=None, out_base=None,
                    triggers=None, device="cpu", compute_type="int8"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("[aiframecut] transcription needs faster-whisper — run 'uv sync' in the skill dir.")

    tmp = Path(tempfile.mkdtemp(prefix="afc_tx_"))
    try:
        wav = tmp / "audio.wav"
        _extract_wav(video, wav)
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        seg_iter, info = model.transcribe(str(wav), language=language, vad_filter=True)
        segments = [{"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
                    for s in seg_iter]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    marks = find_marks(segments, triggers if triggers is not None else DEFAULT_TRIGGERS)
    result = {
        "video": str(video),
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 2),
        "model": model_size,
        "segments": segments,
        "edit_marks": marks,
    }

    base = str(Path(out_base or default_out(video, "")).with_suffix(""))
    Path(base + ".json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(base + ".txt").write_text("\n".join(s["text"] for s in segments) + "\n", encoding="utf-8")
    write_srt(segments, base + ".srt")
    result["_out_base"] = base
    return result
