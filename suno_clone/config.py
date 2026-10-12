from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class Settings:
    backend: str = field(default_factory=lambda: _env("SUNO_CLONE_BACKEND", "mock"))  # mock|acestep|yue2
    workdir: Path = field(default_factory=lambda: Path(_env("SUNO_CLONE_WORKDIR", "./.suno-work")))
    public_base_url: str | None = field(default_factory=lambda: _env("SUNO_CLONE_PUBLIC_BASE_URL"))

    # Limits Suno enforces on its composer (docs/FINDINGS.md section 1).
    max_style_chars: int = 1000
    max_exclude_chars: int = 1000
    max_lyrics_chars: int = 5000
    max_title_chars: int = 100
    max_description_chars: int = 3000
    max_seconds: float = 480.0          # 8 minutes per generation
    variations: int = field(default_factory=lambda: int(_env("SUNO_CLONE_VARIATIONS", "2")))  # Suno returns 2

    # ACE-Step 1.5 REST server (`uv run acestep-api`, default port 8001).
    acestep_url: str = field(default_factory=lambda: _env("ACESTEP_URL", "http://localhost:8001"))
    acestep_api_key: str | None = field(default_factory=lambda: _env("ACESTEP_API_KEY"))
    acestep_model: str | None = field(default_factory=lambda: _env("ACESTEP_MODEL"))  # e.g. acestep-v15-xl-sft
    acestep_base_model: str | None = field(default_factory=lambda: _env("ACESTEP_BASE_MODEL"))  # for stems
    acestep_thinking: bool = field(default_factory=lambda: _env("ACESTEP_THINKING", "1") == "1")

    # YuE2 (in-process, needs `yue2_infer` and a 24 GB GPU). Weights are CC BY-NC 4.0.
    yue2_model: str = field(default_factory=lambda: _env("YUE2_MODEL", "m-a-p/YuE2-3B"))
    yue2_device: str = field(default_factory=lambda: _env("YUE2_DEVICE", "cuda"))

    sample_rate: int = 48_000
    output_format: str = field(default_factory=lambda: _env("SUNO_CLONE_FORMAT", "mp3"))  # mp3|wav|flac
    loudness_target_db: float = -14.0   # streaming loudness target; applied as RMS approximation
    poll_interval: float = 3.0
    timeout_seconds: float = 30 * 60


settings = Settings()
