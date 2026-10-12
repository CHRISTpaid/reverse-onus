"""Suno-style operations on top of an engine.

  generate         custom mode (lyrics + styles) or simple mode (description), 2 songs per call
  extend           continue a clip from a timestamp with new lyrics (engine repaint on a padded
                   copy of the clip's tail), then "Get whole song" stitches the chain
  replace_section  regenerate [start, end] with new lyrics, keep the rest bit-exact
  cover            re-perform a clip or your own upload in a new style
  stems            vocals + instrumental

Every clip keeps a lossless master (master.flac) for later edits and a loudness-normalised
delivery file, plus debug.json with the exact engine request.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import numpy as np

from . import audio, lyrics as L
from .backends import BackendError, EngineTask, get_backend
from .config import settings
from .schemas import (Clip, ConcatRequest, CoverRequest, ExtendRequest, GenerateRequest,
                      ReplaceSectionRequest, StemsRequest)
from .style import compile_style

EXTEND_CONTEXT_SECONDS = 120.0   # how much of the parent the engine hears before the new part
ENGINE_MAX_SECONDS = 600.0       # ACE-Step's 10-minute ceiling


class Store:
    def __init__(self, root: Path | None = None):
        self._root = root
        self.lock = threading.Lock()

    @property
    def root(self) -> Path:
        return Path(self._root or settings.workdir)

    def dir(self, clip_id: str) -> Path:
        d = self.root / clip_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, clip: Clip) -> Clip:
        d = self.dir(clip.id)
        with self.lock:  # write-then-rename so readers never see a half-written file
            tmp = d / f"clip.json.{threading.get_ident()}.tmp"
            tmp.write_text(clip.model_dump_json(indent=2))
            os.replace(tmp, d / "clip.json")
        return clip

    def get(self, clip_id: str) -> Clip:
        p = self.root / clip_id / "clip.json"
        if not clip_id.replace("-", "").isalnum() or not p.exists():
            raise KeyError(clip_id)
        return Clip.model_validate_json(p.read_text())

    def master(self, clip_id: str) -> np.ndarray:
        clip = self.get(clip_id)
        if clip.status != "complete":
            raise BackendError(f"clip {clip_id} isn't complete ({clip.status})")
        return audio.load(self.root / clip_id / "master.flac")


store = Store()


def new_clips(n: int, task: str, title: str = "", **metadata) -> list[Clip]:
    return [store.save(Clip(id=str(uuid.uuid4()), task=task, title=title, metadata=dict(metadata)))
            for _ in range(n)]


def _finish(clip: Clip, y: np.ndarray, meta: dict) -> Clip:
    d = store.dir(clip.id)
    audio.save(y, d / "master.flac")
    name = f"{clip.id}.{settings.output_format}"
    audio.save(y, d / name, loudnorm=True)
    clip.audio_url = f"/files/{clip.id}/{name}"
    clip.duration = round(audio.seconds(y), 3)
    clip.metadata.update(meta)
    clip.status = "complete"
    return store.save(clip)


def _debug(clips: list[Clip], task: EngineTask, extra: dict | None = None) -> None:
    info = {"kind": task.kind, "caption": task.style.caption, "negative": task.style.negative,
            "lyrics_rendered": L.render_tagged(task.song), "duration": task.duration, "seed": task.seed,
            "variations": task.variations, "start": task.start, "end": task.end,
            "cover_strength": task.cover_strength, "style_notes": task.style.notes, "log": task.log,
            **(extra or {})}
    for c in clips:
        (store.dir(c.id) / "debug.json").write_text(json.dumps(info, indent=2, default=str))


def _fail(clips: list[Clip], err: Exception, cancelled: bool = False) -> None:
    for c in clips:
        if c.status != "complete":
            c.status = "cancelled" if cancelled else "error"
            c.error = str(err)
            store.save(c)


def _run(task: EngineTask, clips: list[Clip]):
    backend = get_backend(settings.backend)
    backend.require(task.kind)
    for c in clips:
        c.status = "running"
        store.save(c)
    res = backend.run(task)
    if len(res.files) < len(clips):
        _fail(clips[len(res.files):], BackendError("engine returned fewer songs than requested"))
    return res


def _seed(seed: int | None) -> int:
    return seed if seed is not None else int.from_bytes(uuid.uuid4().bytes[:4], "little") >> 1


# ---------------------------------------------------------------- operations

def generate(req: GenerateRequest, clips: list[Clip], cancel: threading.Event | None = None) -> list[Clip]:
    song = L.parse(req.lyrics)
    spec = compile_style(req.style, req.exclude_styles, vocal_gender=req.vocal_gender,
                         instrumental=req.instrumental, song=song, weirdness=req.weirdness,
                         style_influence=req.style_influence)
    seed = _seed(req.seed)
    task = EngineTask(kind="describe" if req.simple else "generate", style=spec, song=song,
                      out_dir=store.dir(clips[0].id) / "engine", description=req.description,
                      duration=req.duration, seed=seed, variations=len(clips),
                      cancel=cancel or threading.Event())
    est = None if req.simple else L.estimate_seconds(song)
    if task.duration is None and settings.backend != "acestep":
        task.duration = est  # ACE-Step's planner LM picks the length itself, as Suno does
    res = _run(task, clips)
    lyr = res.lyrics if res.lyrics is not None else req.lyrics
    title = req.title or (L.parse(lyr).lyric_lines or [req.description[:40] or "Untitled"])[0][:80]
    for i, (clip, f) in enumerate(zip(clips, res.files)):
        y = audio.load(f)
        if req.duration and audio.seconds(y) > req.duration + 0.5:
            y = audio.fade_out(y[: audio.idx(req.duration)])
        clip.title = clip.title or title
        _finish(clip, y, {"style": req.style, "exclude_styles": req.exclude_styles, "lyrics": lyr,
                          "caption": res.caption or spec.caption, "instrumental": spec.instrumental,
                          "seed": seed + i, "engine": res.meta, "estimated_seconds": est,
                          "description": req.description})
    _debug(clips, task, {"engine_meta": res.meta})
    return clips


def extend(req: ExtendRequest, clips: list[Clip], cancel: threading.Event | None = None) -> list[Clip]:
    parent = store.get(req.clip_id)
    a = store.master(req.clip_id)
    total = audio.seconds(a)
    at = total if req.continue_at is None else min(req.continue_at, total)
    ctx_len = min(at, EXTEND_CONTEXT_SECONDS, ENGINE_MAX_SECONDS - req.duration)
    ctx = a[audio.idx(at - ctx_len): audio.idx(at)]
    src_path = store.dir(clips[0].id) / "engine" / "extend-src.wav"
    src_path.parent.mkdir(parents=True, exist_ok=True)
    audio.save(np.concatenate([ctx, audio.silence(req.duration)]), src_path)
    pm = parent.metadata
    style = req.style or (pm.get("style", "") if req.inherit_style else "")
    exclude = req.exclude_styles or (pm.get("exclude_styles", "") if req.inherit_style else "")
    song = L.parse(req.lyrics)
    spec = compile_style(style, exclude, vocal_gender=req.vocal_gender,
                         instrumental=bool(pm.get("instrumental")) and not song.lyric_lines, song=song,
                         weirdness=req.weirdness, style_influence=req.style_influence)
    seed = _seed(req.seed)
    task = EngineTask(kind="repaint", style=spec, song=song, out_dir=src_path.parent, seed=seed,
                      variations=len(clips), src_audio=src_path, start=audio.seconds(ctx), end=-1,
                      duration=req.duration, cancel=cancel or threading.Event())
    res = _run(task, clips)
    for i, (clip, f) in enumerate(zip(clips, res.files)):
        y = audio.load(f)[len(ctx): len(ctx) + audio.idx(req.duration)]
        clip.title = clip.title or req.title or parent.title
        _finish(clip, y, {"parent_id": parent.id, "continue_at": round(at, 3), "style": style,
                          "exclude_styles": exclude, "lyrics": req.lyrics, "instrumental": spec.instrumental,
                          "seed": seed + i, "engine": res.meta, "context_seconds": round(ctx_len, 3)})
    _debug(clips, task, {"parent_id": parent.id, "continue_at": at})
    return clips


def concat(req: ConcatRequest, clip: Clip) -> Clip:
    """Suno's "Get whole song": root[:T1] + ext1[:T2] + ... + last extension."""
    chain = [store.get(req.clip_id)]
    while chain[0].task == "extend" and chain[0].metadata.get("parent_id"):
        chain.insert(0, store.get(chain[0].metadata["parent_id"]))
        if len(chain) > 200:
            raise BackendError("extend chain too long")
    if len(chain) == 1:
        raise BackendError("this clip isn't an extension; nothing to stitch")
    out = None
    for cur, nxt in zip(chain, chain[1:] + [None]):
        y = store.master(cur.id)
        if nxt is not None:
            y = y[: audio.idx(nxt.metadata["continue_at"])]
        out = y if out is None else audio.crossfade(out, y)
    root = chain[0].metadata
    clip.title = clip.title or chain[0].title
    lyr = "\n\n".join(c.metadata.get("lyrics", "") for c in chain if c.metadata.get("lyrics"))
    return _finish(clip, out, {"parts": [c.id for c in chain], "style": root.get("style", ""),
                               "exclude_styles": root.get("exclude_styles", ""), "lyrics": lyr,
                               "instrumental": root.get("instrumental", False)})


def replace_section(req: ReplaceSectionRequest, clips: list[Clip],
                    cancel: threading.Event | None = None) -> list[Clip]:
    parent = store.get(req.clip_id)
    a = store.master(req.clip_id)
    end = min(req.end, audio.seconds(a))
    if end - req.start < 2:
        raise BackendError("section is outside the song")
    pm = parent.metadata
    song = L.parse(req.lyrics)
    spec = compile_style(req.style or pm.get("style", ""), req.exclude_styles or pm.get("exclude_styles", ""),
                         vocal_gender=req.vocal_gender, instrumental=bool(pm.get("instrumental")),
                         song=song, weirdness=req.weirdness, style_influence=req.style_influence)
    src = store.dir(parent.id) / "master.flac"
    seed = _seed(req.seed)
    task = EngineTask(kind="repaint", style=spec, song=song, out_dir=store.dir(clips[0].id) / "engine",
                      seed=seed, variations=len(clips), src_audio=src, start=req.start, end=end,
                      cancel=cancel or threading.Event())
    res = _run(task, clips)
    for i, (clip, f) in enumerate(zip(clips, res.files)):
        y = audio.splice(a, audio.load(f), req.start, end)
        clip.title = clip.title or parent.title
        _finish(clip, y, {**{k: v for k, v in pm.items() if k in ("style", "exclude_styles", "instrumental")},
                          "parent_id": parent.id, "replaced": [req.start, end], "section_lyrics": req.lyrics,
                          "lyrics": pm.get("lyrics", ""), "seed": seed + i, "engine": res.meta})
    _debug(clips, task, {"parent_id": parent.id})
    return clips


def cover(req: CoverRequest, clips: list[Clip], cancel: threading.Event | None = None) -> list[Clip]:
    pm: dict = {}
    if req.clip_id:
        parent = store.get(req.clip_id)
        store.master(req.clip_id)  # must be complete
        pm, src, title = parent.metadata, store.root / parent.id / "master.flac", parent.title
    else:
        src, title = audio.fetch(req.audio_url, store.dir(clips[0].id) / "engine"), ""
    lyr = req.lyrics if req.lyrics is not None else pm.get("lyrics", "")
    song = L.parse(lyr)
    spec = compile_style(req.style, req.exclude_styles, vocal_gender=req.vocal_gender, song=song,
                         instrumental=bool(pm.get("instrumental")) and not song.lyric_lines,
                         weirdness=req.weirdness, style_influence=req.style_influence)
    seed = _seed(req.seed)
    task = EngineTask(kind="cover", style=spec, song=song, out_dir=store.dir(clips[0].id) / "engine",
                      seed=seed, variations=len(clips), src_audio=Path(src),
                      cover_strength=round(0.2 + 0.8 * req.audio_influence, 3), cancel=cancel or threading.Event())
    res = _run(task, clips)
    for i, (clip, f) in enumerate(zip(clips, res.files)):
        clip.title = clip.title or req.title or (f"{title} (Cover)" if title else "Cover")
        _finish(clip, audio.load(f), {"parent_id": req.clip_id, "source": req.audio_url, "style": req.style,
                                      "exclude_styles": req.exclude_styles, "lyrics": lyr,
                                      "instrumental": spec.instrumental, "seed": seed + i,
                                      "audio_influence": req.audio_influence, "engine": res.meta})
    _debug(clips, task, {"parent_id": req.clip_id})
    return clips


def stems(req: StemsRequest, clips: list[Clip], cancel: threading.Event | None = None) -> list[Clip]:
    """clips[0] <- vocals, clips[1] <- instrumental. Uses Demucs when installed, else the engine."""
    parent = store.get(req.clip_id)
    mix = store.master(req.clip_id)
    src = store.root / parent.id / "master.flac"
    work = store.dir(clips[0].id) / "engine"
    work.mkdir(parents=True, exist_ok=True)
    how = "demucs" if shutil.which("demucs") else settings.backend
    if how == "demucs":
        subprocess.run(["demucs", "--two-stems=vocals", "-o", str(work), str(src)], check=True,
                       capture_output=True)
        found = {p.stem: p for p in work.rglob("*.wav")}
        vocals, inst = audio.load(found["vocals"]), audio.load(found["no_vocals"])
    else:
        task = EngineTask(kind="stems", style=compile_style(""), song=L.parse(""), out_dir=work,
                          variations=1, src_audio=src, stem="vocals", cancel=cancel or threading.Event())
        res = _run(task, clips[:1])
        vocals = audio.load(res.files[0])
        n = min(len(vocals), len(mix))
        vocals = vocals[:n]
        inst = mix[:n] - vocals
    for clip, y, kind in ((clips[0], vocals, "vocals"), (clips[1], inst, "instrumental")):
        clip.title = f"{parent.title} ({kind.title()})"
        _finish(clip, y, {"parent_id": parent.id, "stem": kind, "separator": how})
    return clips


OPS = {"generate": generate, "extend": extend, "replace-section": replace_section, "cover": cover,
       "stems": stems}


def run_op(op: str, req, clips: list[Clip], cancel: threading.Event | None = None) -> list[Clip]:
    """Run an operation, recording failures on the clips instead of raising."""
    cancel = cancel or threading.Event()
    try:
        return OPS[op](req, clips, cancel)
    except Exception as e:  # noqa: BLE001 - surfaced on the clip
        _fail(clips, e, cancelled=cancel.is_set())
        return clips
