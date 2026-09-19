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
_PIPES = {}
def _image_pipe(model: str, img2img: bool):
    """Cached pipelines so a script can generate many images without reloading (~4 s each)."""
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionImg2ImgPipeline, StableDiffusionPipeline
    key = (model, img2img)
    if key not in _PIPES:
        dev = _device(); dtype = torch.float16 if dev == "cuda" else torch.float32
        cls = StableDiffusionImg2ImgPipeline if img2img else StableDiffusionPipeline
        pipe = cls.from_pretrained(model, torch_dtype=dtype, safety_checker=None, requires_safety_checker=False)
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True, final_sigmas_type="sigma_min")
        pipe = pipe.to(dev); pipe.set_progress_bar_config(disable=True)
        _PIPES[key] = pipe
    return _PIPES[key]


def _inpaint_pipe(model: str):
    """Inpainting with any SD1.5 checkpoint (diffusers falls back to masked img2img for 4-channel UNets)."""
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionInpaintPipeline
    key = (model, "inpaint")
    if key not in _PIPES:
        dev = _device(); dtype = torch.float16 if dev == "cuda" else torch.float32
        pipe = StableDiffusionInpaintPipeline.from_pretrained(model, torch_dtype=dtype, safety_checker=None, requires_safety_checker=False)
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True, final_sigmas_type="sigma_min")
        pipe = pipe.to(dev); pipe.set_progress_bar_config(disable=True)
        _PIPES[key] = pipe
    return _PIPES[key]


def inpaint_image(prompt: str, init: str, mask: str, out: str, negative: str = NEG_DEFAULT, steps: int = 30,
                  guidance: float = 7.5, seed: int | None = None, strength: float = 0.9,
                  model: str = DEFAULT_IMAGE_MODEL) -> str:
    """Repaint only the white area of `mask` (e.g. a mouth or the eyes) — the rest of `init` stays pixel-identical.
    This is how to make matching avatar states (talking / blink) from one drawing."""
    _need_ai("inpaint")
    import numpy as np
    import torch
    from PIL import Image
    src = Image.open(init).convert("RGB"); W, H = (src.width // 8) * 8, (src.height // 8) * 8
    src = src.resize((W, H), Image.LANCZOS); m = Image.open(mask).convert("L").resize((W, H), Image.NEAREST)
    pipe = _inpaint_pipe(model)
    s = seed if seed is not None else int.from_bytes(os.urandom(4), "little")
    g = torch.Generator(_device()).manual_seed(s)
    img = pipe(prompt, image=src, mask_image=m, negative_prompt=negative, num_inference_steps=steps,
               guidance_scale=guidance, strength=strength, generator=g, width=W, height=H).images[0]
    # hard-composite: only masked pixels change
    mm = np.asarray(m).astype(np.float32)[..., None] / 255.0
    res = (np.asarray(img).astype(np.float32) * mm + np.asarray(src).astype(np.float32) * (1 - mm)).astype(np.uint8)
    Image.fromarray(res).save(out)
    return out


def remove_background(image: str, out: str) -> str:
    """Cut a subject out onto transparency (rembg / U2-Net). For avatars, stickers, PNGtuber states."""
    _need_ai("cutout")
    from PIL import Image
    from rembg import remove
    im = Image.open(image).convert("RGBA")
    remove(im).save(out)
    return out


def generate_image(prompt: str, out: str, negative: str = NEG_DEFAULT, width: int = 768, height: int = 512,
                   steps: int = 28, guidance: float = 7.0, seed: int | None = None,
                   model: str = DEFAULT_IMAGE_MODEL, count: int = 1,
                   init: str | None = None, strength: float = 0.6) -> list[str]:
    """Text-to-image, or image-to-image when `init` is given (`strength` 0..1 = how much to change).

    img2img is how you keep a consistent world across many images: generate one key painting,
    then derive others from it (same scene at dusk, a closer view, a variant) — and it doubles as
    a "hires fix": upscale a small render, then img2img at the big size with strength ~0.3."""
    _need_ai("imagine")
    import torch
    from PIL import Image
    dev = _device()
    pipe = _image_pipe(model, init is not None)
    width, height = (max(256, (width // 8) * 8), max(256, (height // 8) * 8))
    outs = []
    for i in range(count):
        s = (seed + i) if seed is not None else int.from_bytes(os.urandom(4), "little")
        g = torch.Generator(dev).manual_seed(s)
        if init is not None:
            src = Image.open(init).convert("RGB").resize((width, height), Image.LANCZOS)
            img = pipe(prompt, image=src, strength=strength, negative_prompt=negative,
                       num_inference_steps=steps, guidance_scale=guidance, generator=g).images[0]
        else:
            img = pipe(prompt, negative_prompt=negative, width=width, height=height,
                       num_inference_steps=steps, guidance_scale=guidance, generator=g).images[0]
        p = out if count == 1 else str(Path(out).with_name(f"{Path(out).stem}_{i + 1}{Path(out).suffix}"))
        img.save(p)
        outs.append(f"{p}  (seed {s})")
    return outs


_DEPTH = {}
def depth_map(image: str, out: str, model: str = "depth-anything/Depth-Anything-V2-Small-hf") -> str:
    """Estimate a depth map (white = near) for a painting so `draw` can add real parallax."""
    _need_ai("depth")
    import numpy as np
    from PIL import Image
    from transformers import pipeline
    if model not in _DEPTH:
        _DEPTH[model] = pipeline("depth-estimation", model=model, device=0 if _device() == "cuda" else -1)
    im = Image.open(image).convert("RGB")
    d = _DEPTH[model](im)["depth"]                       # PIL image, relative depth
    a = np.asarray(d, np.float32); a = (a - a.min()) / max(1e-6, a.max() - a.min())
    Image.fromarray((a * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR).save(out)
    return out


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
def _peak_db(path: str) -> float:
    """Peak level of a file in dBFS (via ffmpeg volumedetect)."""
    import re
    import subprocess
    from ._ffmpeg import FFMPEG
    r = subprocess.run([FFMPEG, "-i", path, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else 0.0


def _prep_reference(ref: str, max_seconds: float = 12.0, denoise: bool = False) -> str:
    """Take a file or a folder of recordings; return one 24 kHz mono WAV (<= max_seconds).

    Gain is normalized FIRST (static, to -3 dBFS peak) so quiet recordings are not mistaken for
    noise. Denoising is OFF by default: the model copies whatever it hears in the reference, and
    denoiser artifacts ("squeaky", watery) are far worse than a little room tone. `denoise=True`
    applies a gentle, noise-tracking reduction after the gain stage."""
    from ._ffmpeg import ffmpeg
    p = Path(ref)
    files = sorted(x for x in p.iterdir() if x.suffix.lower() in (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4", ".webm")) if p.is_dir() else [p]
    if not files:
        sys.exit(f"[aiframecut] no audio found at {ref}")
    tmp = Path(tempfile.mkdtemp(prefix="afc_ref_"))
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{f.resolve().as_posix()}'\n" for f in files), encoding="utf-8")
    raw = str(tmp / "raw.wav")
    ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-t", str(max_seconds), "-ac", "1", "-ar", "24000", raw])
    gain = -3.0 - _peak_db(raw)
    chain = f"highpass=f=60,volume={gain:.1f}dB"
    if denoise:
        chain += ",afftdn=nr=10:nf=-60:tn=1"
    out = str(tmp / "ref.wav")
    ffmpeg(["-i", raw, "-af", chain, out])
    return out


def _transcribe_ref(wav: str) -> str:
    from faster_whisper import WhisperModel
    m = WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(wav, vad_filter=True)
    return " ".join(s.text.strip() for s in segs).strip()


def _split_sentences(text: str) -> list[list[str]]:
    """Paragraphs -> sentences. Keeps punctuation; drops empties."""
    import re
    paras = []
    for para in re.split(r"\n\s*\n", text.strip()):
        sents = [x.strip() for x in re.split(r"(?<=[.!?\u2026])\s+", para.replace("\n", " ")) if x.strip()]
        if sents:
            paras.append(sents)
    return paras


def clone_voice(ref: str, text: str, out: str, ref_text: str | None = None, speed: float = 1.0,
                seed: int | None = None, steps: int = 48, pause: float = 0.35, para_pause: float = 0.7,
                denoise: bool = False) -> str:
    """Speak `text` in the voice from `ref` (a file or folder of the user's OWN recordings).

    Generates sentence by sentence and joins them with real pauses (`pause` s between sentences,
    `para_pause` s between paragraphs) — smoother and more natural than one long pass, and pauses are
    never stripped. `steps` = diffusion steps (32 fast, 48 default, 64 best)."""
    _need_ai("clone")
    _patch_torchaudio_load()
    import numpy as np
    import soundfile as sf
    from f5_tts.api import F5TTS
    ref_wav = _prep_reference(ref, denoise=denoise)
    if not ref_text:
        ref_text = _transcribe_ref(ref_wav)
        if not ref_text:
            sys.exit("[aiframecut] couldn't hear any speech in the reference audio — use a clean clip of just the voice.")
    tts = F5TTS()
    pieces, sr = [], 24000
    paras = _split_sentences(text)
    for pi, sents in enumerate(paras):
        for si, sent in enumerate(sents):
            wav, sr, _ = tts.infer(ref_file=ref_wav, ref_text=ref_text, gen_text=sent, speed=speed, seed=seed,
                                   nfe_step=steps, remove_silence=False, show_info=lambda *a, **k: None)
            wav = np.asarray(wav, dtype=np.float32)
            # trim leading/trailing near-silence so our pauses are the only pauses
            thr = 0.01 * max(1e-6, float(np.abs(wav).max())); idx = np.where(np.abs(wav) > thr)[0]
            if len(idx):
                wav = wav[max(0, idx[0] - int(0.05 * sr)):min(len(wav), idx[-1] + int(0.08 * sr))]
            pieces.append(wav)
            last = (si == len(sents) - 1)
            gap = para_pause if (last and pi < len(paras) - 1) else (pause if not last else 0.0)
            if gap:
                pieces.append(np.zeros(int(gap * sr), np.float32))
    audio = np.concatenate(pieces) if pieces else np.zeros(sr, np.float32)
    wav_out = str(Path(out).with_suffix(".wav"))
    sf.write(wav_out, audio, sr)
    if Path(out).suffix.lower() != ".wav":
        from ._ffmpeg import ffmpeg
        ffmpeg(["-i", wav_out, "-b:a", "192k", out])
        os.remove(wav_out)
        return out
    return wav_out
