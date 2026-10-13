"""MCP server: lets Claude Code, Claude Desktop, Codex, ChatGPT or any MCP client make songs.

  suno-clone mcp                      # stdio (Claude Code, Claude Desktop, Codex)
  suno-clone mcp --http --port 8765   # streamable HTTP at /mcp (remote clients, e.g. ChatGPT)

The assistant writes the lyrics and styles; these tools turn them into audio with the configured
engine (SUNO_CLONE_BACKEND=acestep for real songs). Songs take a while, so every tool returns
straight away with clip ids and status, after waiting up to `wait_seconds` for them to finish;
call check_songs to keep waiting.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import lyrics as L, pipeline
from .config import settings
from .schemas import (Clip, ConcatRequest, CoverRequest, ExtendRequest, GenerateRequest,
                      ReplaceSectionRequest, StemsRequest)

INSTRUCTIONS = """Make songs Suno-style with an open-source engine.

Lyrics use section tags on their own lines: [Intro] [Verse 1] [Pre-Chorus] [Chorus] [Bridge]
[Outro] [End]. Add direction after a colon, e.g. [Verse 2: whispered, piano only], and voice
tags like [Female Vocal]. Lines in (parentheses) are backing vocals. Limits: lyrics 5,000 chars,
styles 1,000, title 100, songs up to 8 minutes.

Styles are comma-separated genre, mood, instrument and voice tags ("synthwave, dreamy, 100 bpm,
female vocals"). Put things to avoid in exclude_styles, not as "no X" in styles. weirdness and
style_influence are 0..1 (0.5 default). Each request makes 2 takes by default.

Workflow: create_song -> check_songs until complete -> play the files -> extend_song,
replace_section, cover_song or split_stems on the take the user likes."""

_pool = ThreadPoolExecutor(max_workers=2)
_CANCEL: dict[str, threading.Event] = {}


def _view(c: Clip) -> dict:
    m = c.metadata or {}
    out = {"id": c.id, "status": c.status, "title": c.title, "task": c.task, "duration_s": c.duration}
    if c.status == "complete" and c.audio_url:
        out["file"] = str((pipeline.store.root / c.id / Path(c.audio_url).name).resolve())
        if settings.public_base_url:
            out["url"] = settings.public_base_url.rstrip("/") + c.audio_url
    if c.error:
        out["error"] = c.error
    for k in ("style", "exclude_styles", "parent_id", "continue_at", "stem"):
        if m.get(k):
            out[k] = m[k]
    if m.get("lyrics"):
        out["lyrics_start"] = m["lyrics"][:200]
    return out


def _start(op: str, req, n: int, task: str) -> list[str]:
    clips = pipeline.new_clips(n, task, title=getattr(req, "title", "") or "")
    ev = threading.Event()
    for c in clips:
        _CANCEL[c.id] = ev
    _pool.submit(pipeline.run_op, op, req, clips, ev)
    return [c.id for c in clips]


def check_songs(clip_ids: list[str], wait_seconds: float = 45) -> dict:
    """Status of songs; waits up to wait_seconds (max 300) for unfinished ones."""
    deadline = time.monotonic() + max(0.0, min(wait_seconds, 300))
    while True:
        clips = []
        for i in clip_ids:
            try:
                clips.append(pipeline.store.get(i))
            except KeyError:
                return {"error": f"no song with id {i}"}
        if all(c.status not in ("queued", "running") for c in clips) or time.monotonic() >= deadline:
            done = all(c.status not in ("queued", "running") for c in clips)
            return {"songs": [_view(c) for c in clips],
                    "next": None if done else "still generating; call check_songs again"}
        time.sleep(1.0)


def create_song(lyrics: str = "", style: str = "", exclude_styles: str = "", title: str = "",
                instrumental: bool = False, vocal_gender: str | None = None, weirdness: float = 0.5,
                style_influence: float = 0.5, duration_s: float | None = None, description: str = "",
                takes: int = 2, seed: int | None = None, wait_seconds: float = 45) -> dict:
    """Make a new song (2 takes). Custom mode: lyrics + style. Simple mode: only a description,
    and the engine writes the lyrics. duration_s is optional (10-480); omit it to let the engine pick."""
    req = GenerateRequest(lyrics=lyrics, style=style, exclude_styles=exclude_styles, title=title,
                          instrumental=instrumental, vocal_gender=vocal_gender or None, weirdness=weirdness,
                          style_influence=style_influence, duration=duration_s, description=description,
                          variations=takes, seed=seed)
    return check_songs(_start("generate", req, req.variations, "generate"), wait_seconds)


def extend_song(clip_id: str, lyrics: str = "", continue_at_s: float | None = None, new_part_s: float = 60,
                style: str = "", exclude_styles: str = "", takes: int = 2, seed: int | None = None,
                wait_seconds: float = 45) -> dict:
    """Continue a finished song from continue_at_s (default: its end) with new lyrics.
    Empty style keeps the original's. Use whole_song on the result to get one joined file."""
    req = ExtendRequest(clip_id=clip_id, lyrics=lyrics, continue_at=continue_at_s, duration=new_part_s,
                        style=style, exclude_styles=exclude_styles, variations=takes, seed=seed)
    return check_songs(_start("extend", req, req.variations, "extend"), wait_seconds)


def replace_section(clip_id: str, start_s: float, end_s: float, lyrics: str = "", style: str = "",
                    takes: int = 2, seed: int | None = None, wait_seconds: float = 45) -> dict:
    """Regenerate start_s..end_s of a song with new lyrics; the rest stays as it was."""
    req = ReplaceSectionRequest(clip_id=clip_id, start=start_s, end=end_s, lyrics=lyrics, style=style,
                                variations=takes, seed=seed)
    return check_songs(_start("replace-section", req, req.variations, "replace-section"), wait_seconds)


def cover_song(style: str, clip_id: str | None = None, audio_path: str | None = None,
               lyrics: str | None = None, audio_influence: float = 0.5, takes: int = 2,
               wait_seconds: float = 45) -> dict:
    """Re-perform a song (clip_id) or the user's own audio file (audio_path) in a new style.
    audio_influence 0..1: how closely to follow the original. Only use audio the user owns."""
    req = CoverRequest(clip_id=clip_id, audio_url=audio_path, style=style, lyrics=lyrics,
                       audio_influence=audio_influence, variations=takes)
    return check_songs(_start("cover", req, req.variations, "cover"), wait_seconds)


def split_stems(clip_id: str, wait_seconds: float = 45) -> dict:
    """Split a song into vocals and instrumental."""
    return check_songs(_start("stems", StemsRequest(clip_id=clip_id), 2, "stems"), wait_seconds)


def whole_song(clip_id: str) -> dict:
    """Join an extension chain (give the last extension's id) into one file."""
    clip = pipeline.new_clips(1, "concat")[0]
    try:
        return {"songs": [_view(pipeline.concat(ConcatRequest(clip_id=clip_id), clip))]}
    except Exception as e:  # noqa: BLE001
        pipeline._fail([clip], e)
        return {"error": str(e)}


def list_songs(limit: int = 20) -> dict:
    """Recent songs, newest first."""
    clips = []
    for p in pipeline.store.root.glob("*/clip.json"):
        try:
            clips.append(pipeline.store.get(p.parent.name))
        except (KeyError, ValueError):
            continue
    clips.sort(key=lambda c: c.created_at, reverse=True)
    return {"songs": [_view(c) for c in clips[: max(1, min(limit, 200))]]}


def check_lyrics(lyrics: str) -> dict:
    """How the engine will read a lyric sheet: sections, directions, estimated length."""
    song = L.parse(lyrics)
    return {"sections": [{"section": s.label, "directions": s.descriptors, "lines": len(s.lines)}
                         for s in song.sections],
            "voice": song.voice, "instrumental": song.is_instrumental,
            "estimated_seconds": L.estimate_seconds(song), "characters": len(lyrics),
            "over_limit": len(lyrics) > settings.max_lyrics_chars}


def cancel_songs(clip_ids: list[str]) -> dict:
    """Stop songs that are still generating."""
    for i in clip_ids:
        if i in _CANCEL:
            _CANCEL[i].set()
    return check_songs(clip_ids, 0)


TOOLS = [create_song, check_songs, extend_song, replace_section, cover_song, split_stems, whole_song,
         list_songs, check_lyrics, cancel_songs]


def build_server():
    try:  # MCP Python SDK 2.x
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # 1.x
        from mcp.server.fastmcp import FastMCP as Server
    server = Server(name="suno-clone", instructions=INSTRUCTIONS)
    for fn in TOOLS:
        server.tool()(fn)
    return server


def main(http: bool = False, host: str = "127.0.0.1", port: int = 8765) -> None:
    settings.workdir.mkdir(parents=True, exist_ok=True)
    server = build_server()
    if http:
        server.run("streamable-http", host=host, port=port)
    else:
        server.run("stdio")
