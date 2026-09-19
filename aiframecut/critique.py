"""`critique` / `detect` — honest "does this look AI-made, and why" tooling.

critique: a checklist of the VISIBLE tells people spot in generated art (hands, eyes, text,
nonsense objects, seams that go nowhere, painterly sheen), answered by a small local vision
model plus a few measured signals, with plain-language reasons and fixes.

detect: a local pixel-statistics AI-vs-human classifier — the same kind of thing ZeroGPT/Hive
run — so you can see what a detector would say BEFORE posting. Any raw generated image will
score high here no matter how good it looks; nothing in this file (or this tool) is designed to
change that. The only image that isn't AI-made is one a person drew.
"""
from __future__ import annotations

import json
from pathlib import Path

VLM = "Qwen/Qwen2-VL-2B-Instruct"                 # natively supported by transformers (no remote code)
DETECTOR = "Organika/sdxl-detector"    # best of three tested on anime art (Ateeqq: everything=AI; umm-maybe: SD output=human)

CHECKS = [
    # (key, question, weight, why it matters)
    ("hands", "Are there any hands or fingers visible? If yes, say exactly how many fingers each hand has and whether anything about the hands looks wrong, merged, or extra. If no hands are visible, answer 'no hands'.", 3,
     "AI hands: wrong finger counts, merged or extra fingers, hands fused into objects"),
    ("eyes", "Compare the two eyes: are they the same size, shape, colour and highlight pattern? Answer 'same' or describe the difference.", 2,
     "Mismatched eyes (size, shape, highlight, colour) are the #1 tell in anime-style output"),
    ("text", "Is there any writing, letters, a signature, watermark, or logo anywhere in the image? If yes, quote it and say whether it is readable. If none, answer 'no text'.", 3,
     "Garbled or unreadable 'text' and fake signatures are an instant giveaway"),
    ("objects", "List any objects, accessories, or background elements that are ambiguous, half-formed, duplicated, floating, or don't make sense. If everything makes sense, answer 'none'.", 2,
     "Half-formed props, floating bits, duplicated items"),
    ("clothes", "Do the clothing straps, seams, drawstrings, collars and hair strands connect logically, or do any start or end nowhere / merge into each other? Answer 'logical' or describe the problem.", 2,
     "Straps and strands that go nowhere or fuse into hair/skin"),
    ("limbs", "Count the arms and legs you can see. Does every limb belong to the character and bend the right way? Answer with the counts and 'correct' or the problem.", 3,
     "Extra or impossible limbs"),
    ("style", "Is the shading soft, painterly and gradient-heavy, or flat with clean hard outlines like a cel-shaded sticker? Answer in one sentence.", 0,
     "Over-rendered painterly sheen (informational; the measured 'sheen' check decides)"),
    ("symmetry", "Does the face look believable and consistent (ears, jaw, hair parting, hat placement), or is anything asymmetric in a way that looks like a mistake? Answer 'consistent' or describe it.", 1,
     "Off-model asymmetry"),
]
BAD_WORDS = ["wrong", "merged", "extra", "missing", "unclear", "unreadable", "garbled", "not readable", "illegible", "cannot",
             "doesn't make sense", "does not make sense", "floating", "duplicated", "ambiguous", "half-formed", "nowhere", "fused",
             "different", "larger", "smaller", "mismatch", "asymmetric", "six fingers", "seven", "four fingers", "three fingers", "deformed",
             "odd", "strange", "unusual", "distorted", "blurry", "smudged", "painterly", "soft shading", "gradient-heavy"]
STRONG_BAD = ["wrong", "merged", "extra", "garbled", "unreadable", "illegible", "floating", "nowhere", "fused", "mismatch", "deformed", "distorted", "six fingers", "four fingers"]
OK_WORDS = ["no hands", "no fingers", "no text", "no writing", "no signature", "none", "not visible", "no objects", "nothing",
            "same", "identical", "symmetric", "consistent", "logical", "flat", "cel", "clean", "correct"]


_vlm = None
def _load():
    global _vlm
    if _vlm is None:
        import torch
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = Qwen2VLForConditionalGeneration.from_pretrained(VLM, dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev)
        proc = AutoProcessor.from_pretrained(VLM, min_pixels=256 * 28 * 28, max_pixels=768 * 28 * 28)
        _vlm = (model, proc, dev)
    return _vlm


def _ask(vlm, im, q: str) -> str:
    import torch
    model, proc, dev = vlm
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": q}]}]
    prompt = proc.apply_chat_template(msgs, add_generation_prompt=True)
    inputs = proc(text=[prompt], images=[im], return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=80, do_sample=False)
    return proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()


_det = None
def detect(path: str) -> dict:
    """Pixel-level AI-vs-human classifier (what sites like ZeroGPT/Hive do), run locally.
    Not a truth oracle: heavy edits, scans and compression all shift it — it's for knowing what you'll be told."""
    global _det
    from PIL import Image
    from transformers import pipeline
    if _det is None:
        import torch
        _det = pipeline("image-classification", model=DETECTOR, device=0 if torch.cuda.is_available() else -1)
    res = _det(Image.open(path).convert("RGB"), top_k=None)
    probs = {r["label"].lower(): float(r["score"]) for r in res}
    ai = max((v for k, v in probs.items() if "ai" in k or "fake" in k or "artificial" in k), default=0.0)
    hu = max((v for k, v in probs.items() if "hum" in k or "real" in k), default=1 - ai)
    return {"image": path, "ai": round(ai, 4), "human": round(hu, 4), "label": "AI" if ai >= 0.5 else "human", "raw": probs}


def _measured(path: str) -> list[dict]:
    """Cheap signals that need no model."""
    import numpy as np
    from PIL import Image
    im = Image.open(path); out = []
    w, h = im.size
    if w % 64 == 0 and h % 64 == 0 and w <= 2048:
        out.append({"key": "size", "severity": 1, "note": f"Canvas is {w}x{h} — a typical generator size (multiple of 64). Real drawings rarely land on these exact numbers.",
                    "fix": "Crop to the composition you actually want; don't post the raw square."})
    meta = getattr(im, "text", {}) or {}
    if any(k.lower() in ("parameters", "prompt", "workflow", "comment") for k in meta):
        out.append({"key": "metadata", "severity": 3, "note": "The PNG carries generation metadata (prompt/parameters) inside the file.",
                    "fix": "Export a clean copy; the metadata is a written confession."})
    g = np.asarray(im.convert("L"), np.float32)
    dx = np.abs(np.diff(g, axis=1))[:-1, :]; dy = np.abs(np.diff(g, axis=0))[:, :-1]
    grad = dx + dy; soft = float(((grad >= 1.0) & (grad < 6.0)).mean()); hard = float((grad >= 24).mean())
    if soft > 0.45 and hard < 0.03:
        out.append({"key": "sheen", "severity": 2, "note": f"Shading is mostly soft gradients ({soft:.0%} of pixels) with very few hard edges ({hard:.1%}) — the airbrushed look people call 'AI sheen'.",
                    "fix": "Flatten the shading into 2–3 tones and re-ink the outlines, or redraw over it."})
    return out


def critique(path: str, json_out: str | None = None, quiet: bool = False, with_detect: bool = True, model_id: str | None = None) -> dict:
    """model_id: any transformers-native Qwen2-VL / Qwen2.5-VL checkpoint; bigger = fewer misses (2B is the fast default)."""
    global VLM, _vlm
    if model_id and model_id != VLM:
        VLM = model_id; _vlm = None
    from PIL import Image
    im = Image.open(path).convert("RGB")
    model = _load()
    findings, score, maxscore = [], 0, 0
    for key, q, wt, why in CHECKS:
        ans = _ask(model, im, q); a = ans.lower()
        bad = any(b in a for b in BAD_WORDS); ok = any(o in a for o in OK_WORDS)
        hit = wt > 0 and bad and not (ok and not any(b in a for b in STRONG_BAD))
        maxscore += wt
        if hit:
            score += wt
        findings.append({"key": key, "flag": hit, "weight": wt, "answer": ans, "why": why})
    counts = {}
    for thing in ("characters", "hands", "eyes"):
        c = _ask(model, im, f"How many {thing} are visible in the image? Answer with a single number.")
        digits = "".join(ch for ch in c if ch.isdigit())
        counts[thing] = int(digits) if digits else c
    nchar = counts.get("characters") if isinstance(counts.get("characters"), int) else 1
    if isinstance(counts.get("eyes"), int) and counts["eyes"] not in (0, 2 * max(1, nchar)):
        findings.append({"key": "eye_count", "flag": True, "weight": 2, "answer": f"{counts['eyes']} eyes for {nchar} character(s)", "why": "Wrong number of eyes"}); score += 2; maxscore += 2
    if isinstance(counts.get("hands"), int) and counts["hands"] > 2 * max(1, nchar):
        findings.append({"key": "hand_count", "flag": True, "weight": 3, "answer": f"{counts['hands']} hands for {nchar} character(s)", "why": "Too many hands"}); score += 3; maxscore += 3
    measured = _measured(path)
    for m in measured:
        score += m["severity"]; maxscore += m["severity"]
    pct = int(round(100 * score / max(1, maxscore)))
    verdict = "reads as hand-made" if pct < 20 else "a few tells — fixable" if pct < 45 else "people will call this AI"
    rep = {"image": path, "tells_score": pct, "verdict": verdict, "counts": counts, "findings": findings, "measured": measured}
    if with_detect:
        try:
            rep["detector"] = detect(path)
        except Exception as e:                      # detector is optional
            rep["detector"] = {"error": str(e)[:200]}
    rep["note"] = ("tells_score = what a PERSON will notice. detector = what a pixel-statistics site will say; "
                   "raw generated images score high there regardless of how they look.")
    if json_out:
        Path(json_out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    if not quiet:
        print(f"\n{Path(path).name}: visible AI-tells {pct}/100 — {verdict}")
        for f in findings:
            print(f"  [{'!!' if f['flag'] else 'ok'}] {f['key']:9s} {f['answer'][:150]}")
        for m in measured:
            print(f"  [!!] {m['key']:9s} {m['note']}\n       fix: {m['fix']}")
        flagged = [f for f in findings if f["flag"]]
        if flagged:
            print("  fix first: " + "; ".join(f["why"] for f in flagged[:3]))
        d = rep.get("detector", {})
        if "ai" in d:
            print(f"  detector : {d['label']} (AI {d['ai']:.0%} / human {d['human']:.0%})")
        print("  " + rep["note"])
    return rep
