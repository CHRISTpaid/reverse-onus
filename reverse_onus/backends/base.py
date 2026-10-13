from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from .. import lyrics as L
from ..style import StyleSpec


class BackendError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


@dataclass
class EngineTask:
    """One engine call. kind:
    generate  text (+ lyrics) -> song
    describe  Suno simple mode: description -> lyrics, style and song
    repaint   regenerate [start, end] of src_audio (used for Replace Section and Extend)
    cover     re-perform src_audio in a new style
    stems     isolate `stem` from src_audio
    """
    kind: str
    style: StyleSpec
    song: L.Song
    out_dir: Path
    description: str = ""
    duration: float | None = None
    seed: int | None = None
    variations: int = 2
    src_audio: Path | None = None
    start: float = 0.0
    end: float = -1.0
    cover_strength: float = 1.0
    stem: str = "vocals"
    cancel: threading.Event = field(default_factory=threading.Event)
    log: list[str] = field(default_factory=list)


@dataclass
class EngineResult:
    files: list[Path]
    lyrics: str | None = None    # set when the engine wrote lyrics (simple mode)
    caption: str | None = None
    meta: dict = field(default_factory=dict)


class Backend:
    name = "base"
    capabilities: frozenset[str] = frozenset()

    def run(self, task: EngineTask) -> EngineResult:  # pragma: no cover - interface
        raise NotImplementedError

    def require(self, kind: str) -> None:
        if kind not in self.capabilities:
            raise BackendError(f"the {self.name} engine can't do '{kind}' "
                               f"(it supports: {', '.join(sorted(self.capabilities))})")
