"""HTTP API modelled on Suno's composer actions.

  POST /api/generate          custom or simple mode, returns 2 clips (queued)
  POST /api/extend            continue a clip from a timestamp
  POST /api/concat            "Get whole song" for the last clip of an extend chain
  POST /api/replace-section   regenerate part of a clip
  POST /api/cover             re-perform a clip or your own audio in a new style
  POST /api/stems             vocals + instrumental
  GET  /api/clips/{id}        one clip;  GET /api/feed?ids=a,b  several
  POST /api/clips/{id}/cancel
  POST /api/lyrics/parse      how the clone reads your lyrics (sections, descriptors, length)
  GET  /files/{id}/...        audio, master.flac, debug.json
  GET  /health

Suno has no public developer API, so these routes are our own. Request field names accept
the keys Suno's web app is widely reported to use (tags, negative_tags, prompt,
gpt_description_prompt, make_instrumental, continue_clip_id) as aliases.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import lyrics as L, pipeline
from .config import settings
from .schemas import (Clip, ConcatRequest, CoverRequest, ExtendRequest, GenerateRequest,
                      ReplaceSectionRequest, StemsRequest)

settings.workdir.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Suno clone", version="0.1.0")
app.mount("/files", StaticFiles(directory=settings.workdir), name="files")
pool = ThreadPoolExecutor(max_workers=2)
CANCEL: dict[str, threading.Event] = {}
IDEMPOTENCY: dict[str, tuple[str, list[str]]] = {}
LOCK = threading.Lock()


class ClipsResponse(BaseModel):
    clips: list[Clip]


def _out(clip: Clip, request: Request) -> Clip:
    if clip.audio_url and clip.audio_url.startswith("/"):
        base = (settings.public_base_url or str(request.base_url)).rstrip("/")
        clip = clip.model_copy(update={"audio_url": base + clip.audio_url})
    return clip


def _submit(op: str, body, n: int, task: str, request: Request, key: str | None) -> ClipsResponse:
    fp = op + body.model_dump_json()
    with LOCK:
        if key and key in IDEMPOTENCY:
            old_fp, ids = IDEMPOTENCY[key]
            if old_fp != fp:
                raise HTTPException(409, "Idempotency-Key reused with a different request")
            return ClipsResponse(clips=[_out(pipeline.store.get(i), request) for i in ids])
        clips = pipeline.new_clips(n, task, title=getattr(body, "title", "") or "")
        if key:
            IDEMPOTENCY[key] = (fp, [c.id for c in clips])
    ev = threading.Event()
    for c in clips:
        CANCEL[c.id] = ev
    pool.submit(pipeline.run_op, op, body, clips, ev)
    return ClipsResponse(clips=[_out(c, request) for c in clips])


def _check_parent(clip_id: str | None) -> None:
    if clip_id is None:
        return
    try:
        c = pipeline.store.get(clip_id)
    except KeyError:
        raise HTTPException(404, f"clip {clip_id} not found")
    if c.status != "complete":
        raise HTTPException(409, f"clip {clip_id} is {c.status}")


@app.post("/api/generate", status_code=202, response_model=ClipsResponse)
def generate(body: GenerateRequest, request: Request, idempotency_key: str | None = Header(default=None)):
    return _submit("generate", body, body.variations, "generate", request, idempotency_key)


@app.post("/api/extend", status_code=202, response_model=ClipsResponse)
def extend(body: ExtendRequest, request: Request, idempotency_key: str | None = Header(default=None)):
    _check_parent(body.clip_id)
    return _submit("extend", body, body.variations, "extend", request, idempotency_key)


@app.post("/api/replace-section", status_code=202, response_model=ClipsResponse)
def replace_section(body: ReplaceSectionRequest, request: Request,
                    idempotency_key: str | None = Header(default=None)):
    _check_parent(body.clip_id)
    return _submit("replace-section", body, body.variations, "replace-section", request, idempotency_key)


@app.post("/api/cover", status_code=202, response_model=ClipsResponse)
def cover(body: CoverRequest, request: Request, idempotency_key: str | None = Header(default=None)):
    _check_parent(body.clip_id)
    return _submit("cover", body, body.variations, "cover", request, idempotency_key)


@app.post("/api/stems", status_code=202, response_model=ClipsResponse)
def stems(body: StemsRequest, request: Request, idempotency_key: str | None = Header(default=None)):
    _check_parent(body.clip_id)
    return _submit("stems", body, 2, "stems", request, idempotency_key)


@app.post("/api/concat", response_model=Clip)
def concat(body: ConcatRequest, request: Request):
    _check_parent(body.clip_id)
    clip = pipeline.new_clips(1, "concat")[0]
    try:
        return _out(pipeline.concat(body, clip), request)
    except Exception as e:  # noqa: BLE001
        pipeline._fail([clip], e)
        raise HTTPException(400, str(e))


@app.get("/api/clips/{clip_id}", response_model=Clip)
def get_clip(clip_id: str, request: Request):
    try:
        return _out(pipeline.store.get(clip_id), request)
    except KeyError:
        raise HTTPException(404, "clip not found")


@app.get("/api/feed", response_model=ClipsResponse)
def feed(ids: str, request: Request):
    out = []
    for i in [x for x in ids.split(",") if x]:
        try:
            out.append(_out(pipeline.store.get(i), request))
        except KeyError:
            raise HTTPException(404, f"clip {i} not found")
    return ClipsResponse(clips=out)


@app.post("/api/clips/{clip_id}/cancel", response_model=Clip)
def cancel(clip_id: str, request: Request):
    clip = get_clip(clip_id, request)
    if clip.status in ("queued", "running") and clip_id in CANCEL:
        CANCEL[clip_id].set()
    return clip


class LyricsBody(BaseModel):
    lyrics: str


@app.post("/api/lyrics/parse")
def parse_lyrics(body: LyricsBody):
    song = L.parse(body.lyrics)
    return {"sections": [{"kind": s.kind, "number": s.number, "descriptors": s.descriptors,
                          "lines": s.lines} for s in song.sections],
            "voice": song.voice, "ended": song.ended, "instrumental": song.is_instrumental,
            "estimated_seconds": L.estimate_seconds(song), "engine_lyrics": L.render_tagged(song)}


@app.get("/health")
def health():
    return {"ok": True, "backend": settings.backend}
