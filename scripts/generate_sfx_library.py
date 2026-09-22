#!/usr/bin/env python3
"""Generate a larger curated procedural SFX library (short-form).

Usage (from Klyp-backend):
  uv run python scripts/generate_sfx_library.py
  uv run python scripts/import_sfx_cloudinary.py --force

Produces ~80 mono 48 kHz WAV stubs under app/pipeline/sound_design/sfx_library/
and rewrites manifest.json (keeps commercial placeholders for later packs).
"""

from __future__ import annotations

import json
import math
import random
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_DIR = ROOT / "app" / "pipeline" / "sound_design" / "sfx_library"
MANIFEST_PATH = LIBRARY_DIR / "manifest.json"
SR = 48_000


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def write_wav(path: Path, samples: list[float]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(
        struct.pack("<h", int(_clamp(s) * 32767.0)) for s in samples
    )
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(frames)
    return int(round(1000 * len(samples) / SR))


def env_adsr(
    n: int,
    *,
    attack: float = 0.005,
    decay: float = 0.04,
    sustain: float = 0.35,
    release: float = 0.08,
) -> list[float]:
    a = max(1, int(attack * SR))
    d = max(1, int(decay * SR))
    r = max(1, int(release * SR))
    s_len = max(0, n - a - d - r)
    out: list[float] = []
    for i in range(a):
        out.append(i / a)
    for i in range(d):
        out.append(1.0 - (1.0 - sustain) * (i / d))
    out.extend([sustain] * s_len)
    for i in range(r):
        out.append(sustain * (1.0 - i / r))
    if len(out) < n:
        out.extend([0.0] * (n - len(out)))
    return out[:n]


def tone(
    freq: float,
    duration: float,
    *,
    gain: float = 0.35,
    attack: float = 0.004,
    decay: float = 0.05,
    sustain: float = 0.3,
    release: float = 0.08,
    harmonics: tuple[float, ...] = (1.0,),
) -> list[float]:
    n = max(1, int(duration * SR))
    e = env_adsr(n, attack=attack, decay=decay, sustain=sustain, release=release)
    samples: list[float] = []
    for i in range(n):
        t = i / SR
        s = 0.0
        for hi, amp in enumerate(harmonics, start=1):
            s += amp * math.sin(2 * math.pi * freq * hi * t)
        samples.append(gain * e[i] * s / max(1.0, sum(abs(h) for h in harmonics)))
    return samples


def noise_burst(
    duration: float,
    *,
    gain: float = 0.25,
    attack: float = 0.002,
    release: float = 0.12,
    seed: int = 0,
    band: float = 1.0,
) -> list[float]:
    rng = random.Random(seed)
    n = max(1, int(duration * SR))
    e = env_adsr(n, attack=attack, decay=0.01, sustain=0.55, release=release)
    # simple one-pole lowpass for "band"
    lp = 0.0
    alpha = max(0.02, min(0.95, band))
    samples: list[float] = []
    for i in range(n):
        white = rng.uniform(-1.0, 1.0)
        lp = lp + alpha * (white - lp)
        samples.append(gain * e[i] * lp)
    return samples


def whoosh(duration: float, *, seed: int, gain: float = 0.28, center: float = 0.5) -> list[float]:
    rng = random.Random(seed)
    n = max(1, int(duration * SR))
    samples: list[float] = []
    lp = 0.0
    for i in range(n):
        t = i / n
        # rise then fall
        shape = math.sin(math.pi * t) ** 1.4
        # sweeping filter
        alpha = 0.05 + 0.7 * abs(t - center)
        white = rng.uniform(-1.0, 1.0)
        lp = lp + alpha * (white - lp)
        samples.append(gain * shape * lp)
    return samples


def riser(duration: float, *, seed: int, f0: float = 120.0, f1: float = 900.0) -> list[float]:
    rng = random.Random(seed)
    n = max(1, int(duration * SR))
    samples: list[float] = []
    phase = 0.0
    lp = 0.0
    for i in range(n):
        t = i / n
        freq = f0 + (f1 - f0) * (t**1.6)
        phase += 2 * math.pi * freq / SR
        tone_s = 0.55 * math.sin(phase) + 0.25 * math.sin(phase * 2)
        white = rng.uniform(-1.0, 1.0)
        lp = lp + (0.08 + 0.5 * t) * (white - lp)
        env = (t**0.7) * (1.0 - t) ** 0.15
        samples.append(0.32 * env * (tone_s + 0.45 * lp))
    return samples


def swipe(duration: float, *, seed: int, direction: float = 1.0) -> list[float]:
    # short spectral sweep via FM-ish chirp + noise
    rng = random.Random(seed)
    n = max(1, int(duration * SR))
    samples: list[float] = []
    phase = 0.0
    for i in range(n):
        t = i / n
        if direction >= 0:
            freq = 400 + 2400 * (t**0.8)
        else:
            freq = 2800 - 2200 * (t**0.8)
        phase += 2 * math.pi * freq / SR
        env = math.sin(math.pi * t) ** 1.2
        noise = rng.uniform(-1.0, 1.0) * 0.35
        samples.append(0.3 * env * (math.sin(phase) + noise))
    return samples


def build_specs() -> list[dict]:
    """Curated short-form set mapped to Klyp auto-placement categories."""
    specs: list[dict] = []

    # Chimes / emphasis
    for i, (freq, label, tags) in enumerate(
        [
            (880, "Soft chime", ["soft", "emphasis", "notification"]),
            (1174, "Bright chime", ["bright", "emphasis"]),
            (1318, "Glass ping", ["glass", "emphasis"]),
            (698, "Warm bell", ["warm", "emphasis"]),
            (1568, "Sparkle", ["sparkle", "notification"]),
            (523, "Low chime", ["low", "emphasis"]),
            (987, "Crystal", ["crystal", "bright"]),
            (740, "Soft bell", ["soft", "bell"]),
            (2093, "Hi sparkle", ["sparkle", "hi"]),
            (440, "Deep bell", ["deep", "emphasis"]),
            (1244, "Clear ding", ["clear", "notification"]),
            (1661, "Twinkle", ["twinkle", "bright"]),
        ],
        start=1,
    ):
        specs.append(
            {
                "id": f"chime_{i:02d}",
                "category": "chime",
                "label": label,
                "tags": tags,
                "kind": "chime",
                "freq": freq,
                "duration": 0.16 + (i % 4) * 0.03,
                "seed": 1000 + i,
            }
        )

    # Pops / UI
    pops = [
        (180, "UI pop", ["ui", "click"], 0.06),
        (240, "Soft pop", ["soft", "ui"], 0.07),
        (320, "Snap", ["snap", "click"], 0.05),
        (140, "Thud pop", ["thud", "ui"], 0.08),
        (400, "Bubble", ["bubble", "ui"], 0.09),
        (280, "Tick", ["tick", "ui"], 0.045),
        (210, "Blip", ["blip", "notification"], 0.06),
        (360, "Plick", ["plick", "ui"], 0.05),
        (160, "Muted pop", ["muted", "ui"], 0.07),
        (450, "Hi click", ["click", "hi"], 0.04),
        (120, "Bass pop", ["bass", "ui"], 0.09),
        (300, "Switch", ["switch", "ui"], 0.055),
    ]
    for i, (freq, label, tags, dur) in enumerate(pops, start=1):
        specs.append(
            {
                "id": f"pop_{i:02d}",
                "category": "pop",
                "label": label,
                "tags": tags,
                "kind": "pop",
                "freq": freq,
                "duration": dur,
                "seed": 2000 + i,
            }
        )

    # Whooshes / transitions
    for i, (dur, label, tags) in enumerate(
        [
            (0.28, "Air whoosh", ["transition", "air"]),
            (0.22, "Fast whoosh", ["transition", "fast"]),
            (0.35, "Long whoosh", ["transition", "long"]),
            (0.18, "Short sweep", ["transition", "short"]),
            (0.30, "Cloth whoosh", ["cloth", "transition"]),
            (0.25, "Wind pass", ["wind", "transition"]),
            (0.20, "Quick rush", ["fast", "transition"]),
            (0.32, "Soft flyby", ["soft", "transition"]),
            (0.26, "Stereo whoosh", ["wide", "transition"]),
            (0.24, "Page whoosh", ["page", "transition"]),
            (0.29, "Cinematic whoosh", ["cinematic", "transition"]),
            (0.21, "Snap whoosh", ["snap", "transition"]),
        ],
        start=1,
    ):
        specs.append(
            {
                "id": f"whoosh_{i:02d}",
                "category": "whoosh",
                "label": label,
                "tags": tags,
                "kind": "whoosh",
                "duration": dur,
                "seed": 3000 + i,
            }
        )

    # Risers / zoom
    for i, (dur, f0, f1, label, tags) in enumerate(
        [
            (0.45, 120, 900, "Soft riser", ["zoom", "build"]),
            (0.55, 90, 1100, "Drama riser", ["drama", "zoom"]),
            (0.35, 200, 1400, "Quick riser", ["fast", "zoom"]),
            (0.60, 80, 800, "Deep build", ["deep", "build"]),
            (0.40, 150, 1600, "Bright riser", ["bright", "zoom"]),
            (0.50, 100, 1000, "Tension", ["tension", "build"]),
            (0.38, 180, 1200, "Lift", ["lift", "zoom"]),
            (0.48, 110, 950, "Pulse riser", ["pulse", "build"]),
            (0.42, 140, 1300, "Energy rise", ["energy", "zoom"]),
            (0.52, 95, 1050, "Slow swell", ["slow", "build"]),
        ],
        start=1,
    ):
        specs.append(
            {
                "id": f"riser_{i:02d}",
                "category": "riser",
                "label": label,
                "tags": tags,
                "kind": "riser",
                "duration": dur,
                "f0": f0,
                "f1": f1,
                "seed": 4000 + i,
            }
        )

    # Swipes / overlay cuts
    for i, (dur, direction, label, tags) in enumerate(
        [
            (0.16, 1.0, "Swipe", ["overlay", "cut"]),
            (0.18, -1.0, "Page swipe", ["overlay", "page"]),
            (0.14, 1.0, "Quick swipe", ["fast", "cut"]),
            (0.20, -1.0, "Reverse swipe", ["reverse", "cut"]),
            (0.15, 1.0, "Card swipe", ["card", "overlay"]),
            (0.17, 1.0, "Soft swipe", ["soft", "overlay"]),
            (0.13, -1.0, "Flick", ["flick", "cut"]),
            (0.19, 1.0, "Slide in", ["slide", "overlay"]),
            (0.16, -1.0, "Slide out", ["slide", "cut"]),
            (0.15, 1.0, "Wipe", ["wipe", "overlay"]),
            (0.18, 1.0, "Panel swipe", ["panel", "overlay"]),
            (0.14, -1.0, "Snap wipe", ["snap", "cut"]),
        ],
        start=1,
    ):
        specs.append(
            {
                "id": f"swipe_{i:02d}",
                "category": "swipe",
                "label": label,
                "tags": tags,
                "kind": "swipe",
                "duration": dur,
                "direction": direction,
                "seed": 5000 + i,
            }
        )

    return specs


def synthesize(spec: dict) -> list[float]:
    kind = spec["kind"]
    if kind == "chime":
        return tone(
            float(spec["freq"]),
            float(spec["duration"]),
            gain=0.32,
            attack=0.002,
            decay=0.045,
            sustain=0.22,
            release=0.09,
            harmonics=(1.0, 0.35, 0.12),
        )
    if kind == "pop":
        body = tone(
            float(spec["freq"]),
            float(spec["duration"]),
            gain=0.4,
            attack=0.001,
            decay=0.025,
            sustain=0.05,
            release=0.03,
            harmonics=(1.0, 0.2),
        )
        click = noise_burst(
            min(0.03, float(spec["duration"]) * 0.5),
            gain=0.18,
            attack=0.0005,
            release=0.02,
            seed=int(spec["seed"]),
            band=0.85,
        )
        n = max(len(body), len(click))
        out = [0.0] * n
        for i, v in enumerate(body):
            out[i] += v
        for i, v in enumerate(click):
            out[i] += v
        return out
    if kind == "whoosh":
        return whoosh(
            float(spec["duration"]),
            seed=int(spec["seed"]),
            gain=0.3,
            center=0.45 + (int(spec["seed"]) % 5) * 0.04,
        )
    if kind == "riser":
        return riser(
            float(spec["duration"]),
            seed=int(spec["seed"]),
            f0=float(spec["f0"]),
            f1=float(spec["f1"]),
        )
    if kind == "swipe":
        return swipe(
            float(spec["duration"]),
            seed=int(spec["seed"]),
            direction=float(spec["direction"]),
        )
    raise ValueError(kind)


def main() -> int:
    specs = build_specs()
    # Remove old stub wavs that are not in the new set
    keep_files = {f"{s['id']}.wav" for s in specs}
    for wav in LIBRARY_DIR.glob("*.wav"):
        if wav.name not in keep_files:
            wav.unlink()
            print(f"  removed stale {wav.name}")

    assets: list[dict] = []
    print(f"Generating {len(specs)} SFX…")
    for spec in specs:
        filename = f"{spec['id']}.wav"
        path = LIBRARY_DIR / filename
        samples = synthesize(spec)
        duration_ms = write_wav(path, samples)
        assets.append(
            {
                "id": spec["id"],
                "category": spec["category"],
                "file": filename,
                "label": spec["label"],
                "tags": spec["tags"],
                "duration_ms": duration_ms,
                "public_id": None,
                "secure_url": None,
            }
        )
        print(f"  {filename} ({duration_ms} ms)")

    manifest = {
        "license": (
            "Procedural short-form stubs generated for Klyp auto sound design. "
            "Upload via scripts/import_sfx_cloudinary.py. "
            "Replace/extend with commercial packs (licence export UGC OK) when scaling."
        ),
        "storage": "local",
        "folder": "klyp/sfx",
        "assets": assets,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {MANIFEST_PATH} ({len(assets)} assets)")
    print("Next: uv run python scripts/import_sfx_cloudinary.py --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
