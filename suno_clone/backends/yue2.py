"""YuE2-3B (HKUST/M-A-P), in process. Highest musical quality of the open models in public
blind tests (near-tie with Suno v5, behind v6), but: weights are CC BY-NC 4.0 (individual
creators may sell their songs; companies need a licence), it needs a 24 GB GPU, and it has
no extend/repaint, so this backend only generates.

  hf download m-a-p/YuE2-3B yue2_infer-0.1.5-py3-none-any.whl --local-dir .
  pip install ./yue2_infer-0.1.5-py3-none-any.whl

The call signature follows the model card (pipe(style=, lyrics=, cot=, seed=, cfg_scale=));
not yet run here. Duration isn't a documented input, so the song length comes from lyrics.
"""
from __future__ import annotations

from .. import lyrics as L
from ..config import settings
from .base import Backend, BackendError, EngineResult, EngineTask


class YuE2Backend(Backend):
    name = "yue2"
    capabilities = frozenset({"generate"})

    def __init__(self) -> None:
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            try:
                from yue2_infer import YuE2Pipeline  # type: ignore
            except ImportError as e:  # pragma: no cover - needs the wheel
                raise BackendError("yue2_infer isn't installed; see suno_clone/backends/yue2.py") from e
            self._pipe = YuE2Pipeline.from_pretrained(settings.yue2_model, device=settings.yue2_device,
                                                      progress=False)
        return self._pipe

    def run(self, task: EngineTask) -> EngineResult:
        self.require(task.kind)
        pipe = self._load()
        task.out_dir.mkdir(parents=True, exist_ok=True)
        lyr = "" if task.style.instrumental else L.render_tagged(task.song, lowercase=True,
                                                                  keep_instrumental_sections=False)
        cfg = 1.0 + max(0.0, task.style.style_influence - 0.5)
        if task.duration:
            task.log.append("yue2: duration is not controllable; length follows the lyrics")
        if task.style.negative:
            task.log.append("yue2: no negative prompt input; exclude styles ignored")
        files = []
        for v in range(task.variations):
            path = task.out_dir / f"yue2-{v}.flac"
            song = pipe(style=task.style.caption, lyrics=lyr, cot="full", seed=(task.seed or 0) + v,
                        cfg_scale=cfg)
            song.save(str(path))
            files.append(path)
        return EngineResult(files=files, meta={"engine": "yue2", "cfg_scale": cfg})
