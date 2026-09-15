"""Local generative features — image, music, voice cloning. Optional: `uv sync --extra ai`.

Everything runs on the user's own GPU; nothing is sent anywhere. Models download once
from Hugging Face on first use (image ~2 GB, voice ~1.3 GB, music ~1.5 GB).

Licences (be honest with users): DreamShaper-8 is CreativeML OpenRAIL-M (commercial OK
with its use restrictions); F5-TTS code is MIT but its released weights are CC-BY-NC;
MusicGen weights are CC-BY-NC. Fine for personal projects; check before commercial use.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

DEFAULT_IMAGE_MODEL = "Lykon/dreamshaper-8"          # SD1.5 fine-tune, ~2 GB fp16, much nicer than base 1.5
DEFAULT_MUSIC_MODEL = "facebook/musicgen-small"      # ~1.5 GB
NEG_DEFAULT = ("lowres, blurry, bad anatomy, bad hands, extra fingers, deformed, watermark, "
               "text, signature, jpeg artifacts, worst quality, low quality")


def _need_ai(feature: str):
    try:
        import torch  # noqa: F401
    except ImportError:
        sys.exit(f"[aiframecut] {feature} needs the optional AI extra. In the skill folder run:\n"
                 f"    uv sync --extra ai\n(~3 GB PyTorch + the model on first use; NVIDIA GPU recommended)")


def gpu_info() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return f"torch {torch.__version__} | CUDA {torch.version.cuda} | {p.name} {p.total_memory // (1024 ** 2)} MiB"
        return f"torch {torch.__version__} | CUDA not available (CPU only — slow)"
    except ImportError:
        return "not installed (uv sync --extra ai)"


def _device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


# ------------------------------------------------------------------- image
def generate_image(prompt: str, out: str, negative: str = NEG_DEFAULT, width: int = 768, height: int = 512,
                   steps: int = 28, guidance: float = 7.0, seed: int | None = None,
                   model: str = DEFAULT_IMAGE_MODEL, count: int = 1) -> list[str]:
    _need_ai("imagine")
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionPipeline
    dev = _device()
    dtype = torch.float16 if dev == "cuda" else torch.float32
    pipe = StableDiffusionPipeline.from_pretrained(model, torch_dtype=dtype, safety_checker=None, requires_safety_checker=False)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True, final_sigmas_type="sigma_min")
    pipe = pipe.to(dev)
    pipe.set_progress_bar_config(disable=True)
    width, height = (max(256, (width // 8) * 8), max(256, (height // 8) * 8))
    outs = []
    for i in range(count):
        s = (seed + i) if seed is not None else int.from_bytes(os.urandom(4), "little")
        g = torch.Generator(dev).manual_seed(s)
        img = pipe(prompt, negative_prompt=negative, width=width, height=height,
                   num_inference_steps=steps, guidance_scale=guidance, generator=g).images[0]
        p = out if count == 1 else str(Path(out).with_name(f"{Path(out).stem}_{i + 1}{Path(out).suffix}"))
        img.save(p)
        outs.append(f"{p}  (seed {s})")
    return outs


# ------------------------------------------------------------------- music
def generate_music(prompt: str, out: str, seconds: float = 10.0, model: str = DEFAULT_MUSIC_MODEL,
                   seed: int | None = None, guidance: float = 3.0) -> str:
    _need_ai("compose")
    import scipy.io.wavfile
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration
    dev = _device()
    proc = AutoProcessor.from_pretrained(model)
    m = MusicgenForConditionalGeneration.from_pretrained(model).to(dev)
    if seed is not None:
        torch.manual_seed(seed)
    inputs = proc(text=[prompt], padding=True, return_tensors="pt").to(dev)
    tokens = int(min(30, seconds) * 50)          # MusicGen frame rate is 50 Hz; ~30 s max per pass
    with torch.no_grad():
        audio = m.generate(**inputs, max_new_tokens=tokens, do_sample=True, guidance_scale=guidance)
    sr = m.config.audio_encoder.sampling_rate
    wav = audio[0, 0].float().cpu().numpy()
    wav_path = str(Path(out).with_suffix(".wav"))
    scipy.io.wavfile.write(wav_path, sr, wav)
    if Path(out).suffix.lower() != ".wav":     # mp3 / m4a etc. via ffmpeg
        from ._ffmpeg import ffmpeg
        ffmpeg(["-i", wav_path, "-b:a", "192k", out])
        os.remove(wav_path)
        return out
    return wav_path


def _patch_torchaudio_load():
    """Newer torchaudio routes `load` through torchcodec, which needs FFmpeg *shared* DLLs and
    breaks on many Windows installs. F5-TTS only calls torchaudio.load once (for the reference
    clip), so we swap in a soundfile-based loader with the same return shape: (tensor[ch, n], sr)."""
    import soundfile as sf
    import torch
    import torchaudio

    def _load(path, *a, **k):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)   # (frames, channels)
        return torch.from_numpy(data.T.copy()), sr
    torchaudio.load = _load


# -------------------------------------------------------------- voice clone
def _prep_reference(ref: str, max_seconds: float = 11.0) -> str:
    """Take a file or a folder of recordings; return one clean 24 kHz mono WAV (<= max_seconds)."""
    from ._ffmpeg import ffmpeg
    p = Path(ref)
    files = sorted(x for x in p.iterdir() if x.suffix.lower() in (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4", ".webm")) if p.is_dir() else [p]
    if not files:
        sys.exit(f"[aiframecut] no audio found at {ref}")
    tmp = Path(tempfile.mkdtemp(prefix="afc_ref_"))
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{f.resolve().as_posix()}'\n" for f in files), encoding="utf-8")
    out = str(tmp / "ref.wav")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-t", str(max_seconds),
            "-af", "afftdn=nf=-22,loudnorm=I=-18:TP=-2", "-ac", "1", "-ar", "24000", out])
    return out


def _transcribe_ref(wav: str) -> str:
    from faster_whisper import WhisperModel
    m = WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(wav, vad_filter=True)
    return " ".join(s.text.strip() for s in segs).strip()


def clone_voice(ref: str, text: str, out: str, ref_text: str | None = None, speed: float = 1.0,
                seed: int | None = None) -> str:
    """Speak `text` in the voice from `ref` (a file or folder of the user's OWN recordings)."""
    _need_ai("clone")
    _patch_torchaudio_load()
    from f5_tts.api import F5TTS
    ref_wav = _prep_reference(ref)
    if not ref_text:
        ref_text = _transcribe_ref(ref_wav)
        if not ref_text:
            sys.exit("[aiframecut] couldn't hear any speech in the reference audio — use a clean clip of just the voice.")
    tts = F5TTS()
    wav_out = str(Path(out).with_suffix(".wav"))
    tts.infer(ref_file=ref_wav, ref_text=ref_text, gen_text=text, file_wave=wav_out,
              speed=speed, seed=seed, remove_silence=True)
    if Path(out).suffix.lower() != ".wav":
        from ._ffmpeg import ffmpeg
        ffmpeg(["-i", wav_out, "-b:a", "192k", out])
        os.remove(wav_out)
        return out
    return wav_out
