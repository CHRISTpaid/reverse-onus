"""Deterministic offline engine for tests and wiring: synthesises chords plus a 'voice' line
for sections with lyrics. Sounds like a test tone, not music."""
from __future__ import annotations

import numpy as np

from .. import audio
from ..config import settings
from .. import lyrics as L
from .base import Backend, EngineResult, EngineTask

SR = settings.sample_rate
CHORDS = [(261.6, 329.6, 392.0), (220.0, 261.6, 329.6), (174.6, 220.0, 261.6), (196.0, 246.9, 293.7)]


def _synth(seconds: float, seed: int, vocal_ratio: float, bpm: float = 120.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = audio.idx(seconds)
    t = np.arange(n) / SR
    beat = 60.0 / bpm
    bar = (t // (4 * beat)).astype(int)
    x = np.zeros(n, dtype=np.float32)
    detune = 1 + 0.01 * rng.standard_normal()
    for i, chord in enumerate(CHORDS):
        m = (bar % 4) == i
        for f in chord:
            x[m] += 0.08 * np.sin(2 * np.pi * f * detune * t[m])
    kick = np.exp(-((t % beat) / 0.03)) * np.sin(2 * np.pi * 60 * (t % beat))
    x += 0.3 * kick.astype(np.float32)
    if vocal_ratio > 0:
        melody = 440 * 2 ** (rng.integers(0, 8, size=int(seconds / beat) + 2) / 12)
        f = melody[(t // beat).astype(int)]
        voice = 0.12 * np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)) * (0.6 + 0.4 * np.sin(2 * np.pi * 5 * t))
        x[: int(n * vocal_ratio)] += voice[: int(n * vocal_ratio)].astype(np.float32)
    st = np.stack([x, np.roll(x, 7)], axis=1)
    return st.astype(np.float32)


class MockBackend(Backend):
    name = "mock"
    capabilities = frozenset({"generate", "describe", "repaint", "cover", "stems"})

    def run(self, task: EngineTask) -> EngineResult:
        task.out_dir.mkdir(parents=True, exist_ok=True)
        seed = task.seed if task.seed is not None else 0
        files, lyr, cap = [], None, None
        song = task.song
        if task.kind == "describe":
            lyr = "[Verse]\n" + task.description[:80] + "\n\n[Chorus]\nla la la"
            cap = "pop, upbeat"
            song = L.parse(lyr)
        for v in range(task.variations if task.kind != "stems" else 1):
            s = seed + v
            vocal = 0.0 if task.style.instrumental or song.is_instrumental else 0.8
            if task.kind in ("generate", "describe"):
                dur = task.duration or L.estimate_seconds(song)
                y = _synth(dur, s, vocal)
            else:
                src = audio.load(task.src_audio)
                if task.kind == "repaint":
                    end = audio.seconds(src) if task.end < 0 else task.end
                    new = _synth(audio.seconds(src), s + 1000, vocal)
                    y = src.copy()
                    a, b = audio.idx(task.start), audio.idx(end)
                    y[a:b] = new[a:b]
                elif task.kind == "cover":
                    env = np.abs(src).mean(axis=1, keepdims=True)
                    y = _synth(audio.seconds(src), s + 2000, vocal) * (0.5 + task.cover_strength * env * 4)
                else:  # stems: crude band split, enough to test the plumbing
                    y = src * 0.5
            files.append(audio.save(y, task.out_dir / f"mock-{task.kind}-{v}.wav"))
        return EngineResult(files=files, lyrics=lyr, caption=cap, meta={"engine": "mock"})
