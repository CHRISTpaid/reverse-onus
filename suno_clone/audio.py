"""Audio helpers on top of ffmpeg and numpy (no other audio libraries needed).

Arrays are float32, shape (samples, 2), at settings.sample_rate unless stated.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import numpy as np

from .config import settings


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is required (install it and make sure it is on PATH)")
    return exe


def load(path: str | Path, sr: int | None = None, channels: int = 2) -> np.ndarray:
    sr = sr or settings.sample_rate
    out = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", str(channels),
                          "-ar", str(sr), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).reshape(-1, channels).copy()


def save(x: np.ndarray, path: str | Path, sr: int | None = None, *, loudnorm: bool = False) -> Path:
    """Write wav/mp3/flac by extension. loudnorm applies EBU R128 to settings.loudness_target_db."""
    sr = sr or settings.sample_rate
    path = Path(path)
    x = np.ascontiguousarray(np.clip(x, -1, 1).astype(np.float32))
    ch = 1 if x.ndim == 1 else x.shape[1]
    cmd = [_ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(ch), "-i", "-"]
    if loudnorm:
        cmd += ["-af", f"loudnorm=I={settings.loudness_target_db}:TP=-1:LRA=11", "-ar", str(sr)]
    ext = path.suffix.lower()
    if ext == ".mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "320k"]
    elif ext == ".flac":
        cmd += ["-c:a", "flac"]
    else:
        cmd += ["-c:a", "pcm_s16le"]
    subprocess.run(cmd + [str(path)], input=x.tobytes(), check=True, capture_output=True)
    return path


def seconds(x: np.ndarray, sr: int | None = None) -> float:
    return len(x) / float(sr or settings.sample_rate)


def idx(t: float, sr: int | None = None) -> int:
    return int(round(t * (sr or settings.sample_rate)))


def silence(sec: float, sr: int | None = None) -> np.ndarray:
    return np.zeros((idx(sec, sr), 2), dtype=np.float32)


def crossfade(a: np.ndarray, b: np.ndarray, sec: float = 0.05, sr: int | None = None) -> np.ndarray:
    n = min(idx(sec, sr), len(a), len(b))
    if n == 0:
        return np.concatenate([a, b])
    ramp = np.linspace(0, 1, n, dtype=np.float32)[:, None]
    mid = a[-n:] * (1 - ramp) + b[:n] * ramp
    return np.concatenate([a[:-n], mid, b[n:]])


def splice(original: np.ndarray, new: np.ndarray, start: float, end: float, fade: float = 0.25,
           sr: int | None = None) -> np.ndarray:
    """Keep `original` outside [start, end] and `new` inside it, with crossfades at both seams."""
    s, e = idx(start, sr), min(idx(end, sr), len(original))
    new = new[: len(original)] if len(new) >= len(original) else np.concatenate(
        [new, original[len(new):]])
    out = original.copy()
    out[s:e] = new[s:e]
    n = idx(fade, sr)
    for seam, fwd in ((s, True), (e, False)):
        a, b = max(seam - n // 2, 0), min(seam + n // 2, len(out))
        if b <= a:
            continue
        ramp = np.linspace(0, 1, b - a, dtype=np.float32)[:, None]
        if not fwd:
            ramp = 1 - ramp
        out[a:b] = original[a:b] * (1 - ramp) + new[a:b] * ramp
    return out


def fade_out(x: np.ndarray, sec: float = 2.0, sr: int | None = None) -> np.ndarray:
    n = min(idx(sec, sr), len(x))
    if n:
        x = x.copy()
        x[-n:] *= np.linspace(1, 0, n, dtype=np.float32)[:, None]
    return x


def fetch(src: str, dest_dir: Path) -> Path:
    """Local path or http(s) URL -> local file."""
    if src.startswith(("http://", "https://")):
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = Path(src.split("?")[0]).name or "input.audio"
        dest = dest_dir / f"upload-{name}"
        with httpx.stream("GET", src, follow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return dest
    p = Path(src).expanduser()
    if not p.exists():
        raise FileNotFoundError(src)
    return p
