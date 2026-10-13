"""Song-level features with numpy only, plus optional lyric scoring.

  tempo (BPM), key, loudness, brightness, dynamics, section boundaries, vocal-band share
  lyrics_wer  needs `faster-whisper` (pip install faster-whisper); skipped when missing
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .. import audio

SR = 22050
HOP = 512
NFFT = 2048
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _stft(x: np.ndarray) -> np.ndarray:
    n = 1 + max(0, (len(x) - NFFT) // HOP)
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(NFFT)[None, :]
    return np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)


def tempo(S: np.ndarray) -> float:
    flux = np.maximum(0, np.diff(np.log1p(S), axis=0)).sum(axis=1)
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    fps = SR / HOP
    lags = np.arange(len(ac))
    bpm = 60 * fps / np.maximum(lags, 1)
    ok = (bpm >= 60) & (bpm <= 200)
    if not ok.any():
        return 0.0
    # mild preference for 90-140 BPM, where most pop sits
    w = ac * np.exp(-0.5 * (np.log2(np.maximum(bpm, 1) / 115) / 0.9) ** 2)
    best = lags[ok][np.argmax(w[ok])]
    return round(float(60 * fps / best), 1)


def chroma(S: np.ndarray) -> np.ndarray:
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    ok = (freqs > 55) & (freqs < 4200)
    pcs = (np.round(12 * np.log2(freqs[ok] / 261.63)) % 12).astype(int)
    C = np.zeros((S.shape[0], 12), dtype=np.float32)
    for pc in range(12):
        C[:, pc] = S[:, ok][:, pcs == pc].sum(axis=1)
    return C / (C.sum(axis=1, keepdims=True) + 1e-9)


def key(C: np.ndarray) -> tuple[str, float]:
    prof = C.mean(axis=0)
    best, score = "", -2.0
    for i in range(12):
        for name, tmpl in (("major", MAJOR), ("minor", MINOR)):
            r = float(np.corrcoef(prof, np.roll(tmpl, i))[0, 1])
            if r > score:
                best, score = f"{NOTES[i]} {name}", r
    return best, round(score, 3)


def boundaries(C: np.ndarray, kernel_s: float = 4.0) -> list[float]:
    fps = SR / HOP
    step = max(1, int(fps / 2))  # 2 frames per second
    F = C[::step]
    F = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)
    K = int(kernel_s * 2)
    if len(F) < 2 * K + 2:
        return []
    sim = F @ F.T
    sign = np.ones((2 * K, 2 * K))
    sign[:K, K:] = sign[K:, :K] = -1
    nov = np.array([(sim[i - K:i + K, i - K:i + K] * sign).sum() if K <= i < len(F) - K else 0.0
                    for i in range(len(F))])
    thr = nov.mean() + nov.std()
    peaks = [i for i in range(1, len(nov) - 1) if nov[i] > thr and nov[i] >= nov[i - 1] and nov[i] >= nov[i + 1]]
    out: list[float] = []
    for p in peaks:
        t = p / 2.0
        if not out or t - out[-1] > 8:
            out.append(round(t, 1))
    return out


def features(path: str | Path) -> dict:
    st = audio.load(path, sr=SR)
    x = st.mean(axis=1)
    if len(x) < NFFT * 4:
        raise ValueError(f"{path} is too short to analyse")
    S = _stft(x)
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    power = S ** 2
    C = chroma(S)
    k, kconf = key(C)
    frame_rms = np.sqrt((x[: len(x) // HOP * HOP].reshape(-1, HOP) ** 2).mean(axis=1)) + 1e-9
    loud = 20 * np.log10(frame_rms)
    vocal_band = (freqs > 300) & (freqs < 3400)
    side = st[:, 0] - st[:, 1]
    return {
        "duration": round(len(x) / SR, 2),
        "tempo_bpm": tempo(S),
        "key": k, "key_confidence": kconf,
        "rms_db": round(float(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)), 2),
        "dynamic_range_db": round(float(np.percentile(loud, 95) - np.percentile(loud, 10)), 2),
        "brightness_hz": round(float((power * freqs).sum() / (power.sum() + 1e-9)), 1),
        "vocal_band_share": round(float(power[:, vocal_band].sum() / (power.sum() + 1e-9)), 3),
        "stereo_width": round(float(np.sqrt((side ** 2).mean()) / (np.sqrt((x ** 2).mean()) + 1e-9)), 3),
        "boundaries_s": boundaries(C),
        "chroma_profile": [round(float(v), 4) for v in C.mean(axis=0)],
    }


def _words(t: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", t.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = _words(ref), _words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return round(d[-1] / len(r), 3)


def lyrics_wer(path: str | Path, lyrics_text: str) -> float | None:
    """Word error rate of the sung lyrics against the requested ones (None without faster-whisper)."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    model = WhisperModel("small", compute_type="int8")
    segs, _ = model.transcribe(str(path), vad_filter=True)
    return wer(lyrics_text, " ".join(s.text for s in segs))
