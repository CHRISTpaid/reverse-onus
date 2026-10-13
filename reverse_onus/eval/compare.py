"""Compare a clone song with a Suno song made from the same prompt (both your own files).

Suno has no public API, so the reference is a song you generated in your own account and
downloaded. Exact matches aren't the goal (two Suno runs of one prompt differ too); the
report shows whether the clone lands in the same musical place and how well it sings the
lyrics. Generate the same prompt twice on Suno to get the noise floor.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import lyrics as L
from .metrics import features, lyrics_wer

RELATIVE = {"C major": "A minor", "G major": "E minor", "D major": "B minor", "A major": "F# minor",
            "E major": "C# minor", "B major": "G# minor", "F# major": "D# minor", "C# major": "A# minor",
            "F major": "D minor", "A# major": "G minor", "D# major": "C minor", "G# major": "F minor"}


def _tempo_match(a: float, b: float) -> float:
    if not a or not b:
        return 0.0
    r = min(abs(np.log2(a / b) - k) for k in (-1, 0, 1))  # half/double time counts
    return round(float(max(0.0, 1 - r / 0.15)), 3)


def _key_match(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if RELATIVE.get(a) == b or RELATIVE.get(b) == a:
        return 0.5
    return 0.0


def compare(clone: str | Path, reference: str | Path, lyrics: str = "") -> dict:
    fa, fb = features(clone), features(reference)
    ca, cb = np.array(fa["chroma_profile"]), np.array(fb["chroma_profile"])
    sim = {
        "tempo": _tempo_match(fa["tempo_bpm"], fb["tempo_bpm"]),
        "key": _key_match(fa["key"], fb["key"]),
        "harmony": round(float(ca @ cb / (np.linalg.norm(ca) * np.linalg.norm(cb) + 1e-9)), 3),
        "duration": round(min(fa["duration"], fb["duration"]) / max(fa["duration"], fb["duration"]), 3),
        "brightness": round(min(fa["brightness_hz"], fb["brightness_hz"]) /
                            max(fa["brightness_hz"], fb["brightness_hz"], 1e-9), 3),
        "loudness": round(float(max(0.0, 1 - abs(fa["rms_db"] - fb["rms_db"]) / 12)), 3),
        "sections": round(1 / (1 + abs(len(fa["boundaries_s"]) - len(fb["boundaries_s"]))), 3),
    }
    weights = {"tempo": 2, "key": 1, "harmony": 1, "duration": 1, "brightness": 1, "loudness": 1, "sections": 1}
    report = {"clone": fa, "reference": fb, "similarity": sim,
              "overall": round(sum(sim[k] * w for k, w in weights.items()) / sum(weights.values()), 3)}
    text = L.plain_text(L.parse(lyrics)) if lyrics else ""
    if text:
        report["lyrics_wer"] = {"clone": lyrics_wer(clone, text), "reference": lyrics_wer(reference, text)}
    return report
