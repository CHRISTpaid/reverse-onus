"""reverse-onus command line.

  reverse-onus generate --style "indie pop, female vocals" --lyrics song.txt
  reverse-onus generate --describe "a sad country song about a lost dog"
  reverse-onus extend CLIP_ID --at 95 --lyrics verse3.txt
  reverse-onus whole CLIP_ID
  reverse-onus replace CLIP_ID --start 30 --end 45 --lyrics new-chorus.txt
  reverse-onus cover CLIP_ID|FILE --style "lofi jazz" [--influence 0.7]
  reverse-onus stems CLIP_ID
  reverse-onus parse song.txt
  reverse-onus compare clone.mp3 suno.mp3 [--lyrics song.txt]
  reverse-onus ab cases.json --out ab-runs/
  reverse-onus serve --port 8000          # API + studio page at http://localhost:8000
  reverse-onus mcp [--http]               # MCP server for AI assistants
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import lyrics as L, pipeline
from .config import settings


def _text(v: str | None) -> str:
    if not v:
        return ""
    p = Path(v)
    return p.read_text() if p.exists() and p.is_file() else v


def _sound(p: argparse.ArgumentParser) -> None:
    p.add_argument("--style", default="")
    p.add_argument("--exclude", default="")
    p.add_argument("--vocal", choices=["male", "female"])
    p.add_argument("--weirdness", type=float, default=0.5)
    p.add_argument("--style-influence", type=float, default=0.5)
    p.add_argument("--seed", type=int)
    p.add_argument("--variations", type=int, default=settings.variations)


def _sound_kwargs(a) -> dict:
    return dict(style=a.style, exclude_styles=a.exclude, vocal_gender=a.vocal, weirdness=a.weirdness,
                style_influence=a.style_influence, seed=a.seed, variations=a.variations)


def _print(clips) -> int:
    rc = 0
    for c in clips:
        where = (settings.workdir / c.id / Path(c.audio_url).name) if c.audio_url else None
        print(json.dumps({"id": c.id, "status": c.status, "title": c.title, "duration": c.duration,
                          "file": str(where) if where else None, "error": c.error}))
        rc |= c.status != "complete"
    return rc


def main(argv: list[str] | None = None) -> int:
    from .schemas import (ConcatRequest, CoverRequest, ExtendRequest, GenerateRequest,
                          ReplaceSectionRequest, StemsRequest)
    ap = argparse.ArgumentParser(prog="reverse-onus", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    _sound(g)
    g.add_argument("--lyrics", help="text or a file path")
    g.add_argument("--describe", help="simple mode: a song description")
    g.add_argument("--title", default="")
    g.add_argument("--instrumental", action="store_true")
    g.add_argument("--duration", type=float)
    e = sub.add_parser("extend")
    _sound(e)
    e.add_argument("clip_id")
    e.add_argument("--at", type=float)
    e.add_argument("--lyrics")
    e.add_argument("--duration", type=float, default=60)
    w = sub.add_parser("whole")
    w.add_argument("clip_id")
    r = sub.add_parser("replace")
    _sound(r)
    r.add_argument("clip_id")
    r.add_argument("--start", type=float, required=True)
    r.add_argument("--end", type=float, required=True)
    r.add_argument("--lyrics")
    c = sub.add_parser("cover")
    _sound(c)
    c.add_argument("source", help="clip id or audio file/URL")
    c.add_argument("--lyrics")
    c.add_argument("--influence", type=float, default=0.5)
    s = sub.add_parser("stems")
    s.add_argument("clip_id")
    pa = sub.add_parser("parse")
    pa.add_argument("lyrics")
    cm = sub.add_parser("compare")
    cm.add_argument("clone")
    cm.add_argument("reference")
    cm.add_argument("--lyrics")
    ab = sub.add_parser("ab")
    ab.add_argument("cases")
    ab.add_argument("--out", default="ab-runs")
    mc = sub.add_parser("mcp", help="MCP server for Claude Code, Codex, ChatGPT and other assistants")
    mc.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    mc.add_argument("--host", default="127.0.0.1")
    mc.add_argument("--port", type=int, default=8765)
    sv = sub.add_parser("serve", help="studio page and API at http://localhost:8000")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    for p in (mc, sv):
        p.add_argument("--engine", choices=["acestep", "yue2", "mock"],
                       help="music engine (default: REVERSE_ONUS_BACKEND, else mock)")
    a = ap.parse_args(argv)
    if getattr(a, "engine", None):
        settings.backend = a.engine

    if a.cmd == "generate":
        req = GenerateRequest(lyrics=_text(a.lyrics), description=a.describe or "", title=a.title,
                              instrumental=a.instrumental, duration=a.duration, **_sound_kwargs(a))
        return _print(pipeline.run_op("generate", req, pipeline.new_clips(req.variations, "generate")))
    if a.cmd == "extend":
        req = ExtendRequest(clip_id=a.clip_id, continue_at=a.at, lyrics=_text(a.lyrics),
                            duration=a.duration, **_sound_kwargs(a))
        return _print(pipeline.run_op("extend", req, pipeline.new_clips(req.variations, "extend")))
    if a.cmd == "whole":
        return _print([pipeline.concat(ConcatRequest(clip_id=a.clip_id), pipeline.new_clips(1, "concat")[0])])
    if a.cmd == "replace":
        req = ReplaceSectionRequest(clip_id=a.clip_id, start=a.start, end=a.end, lyrics=_text(a.lyrics),
                                    **_sound_kwargs(a))
        return _print(pipeline.run_op("replace-section", req, pipeline.new_clips(req.variations, "replace-section")))
    if a.cmd == "cover":
        is_clip = (settings.workdir / a.source / "clip.json").exists()
        req = CoverRequest(clip_id=a.source if is_clip else None, audio_url=None if is_clip else a.source,
                           lyrics=_text(a.lyrics) if a.lyrics else None, audio_influence=a.influence,
                           **_sound_kwargs(a))
        return _print(pipeline.run_op("cover", req, pipeline.new_clips(req.variations, "cover")))
    if a.cmd == "stems":
        return _print(pipeline.run_op("stems", StemsRequest(clip_id=a.clip_id), pipeline.new_clips(2, "stems")))
    if a.cmd == "parse":
        song = L.parse(_text(a.lyrics))
        print(json.dumps({"sections": [vars(s) for s in song.sections], "voice": song.voice,
                          "estimated_seconds": L.estimate_seconds(song),
                          "engine_lyrics": L.render_tagged(song)}, indent=2))
        return 0
    if a.cmd == "compare":
        from .eval.compare import compare
        print(json.dumps(compare(a.clone, a.reference, _text(a.lyrics)), indent=2))
        return 0
    if a.cmd == "ab":
        return run_ab(Path(a.cases), Path(a.out))
    if a.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main(http=a.http, host=a.host, port=a.port)
        return 0
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("reverse_onus.server:app", host=a.host, port=a.port)
        return 0
    return 2


def run_ab(cases_path: Path, out: Path) -> int:
    """cases.json: [{"name", "reference": "my-suno-song.mp3", "style", "lyrics", "exclude",
    "instrumental", "seed"}]. Generates each case on the clone, scores both variations against
    your Suno download, writes <out>/<name>/report.json and <out>/summary.json."""
    from .eval.compare import compare
    from .schemas import GenerateRequest
    cases = json.loads(cases_path.read_text())
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for case in cases:
        lyr = _text(case.get("lyrics"))
        req = GenerateRequest(style=case.get("style", ""), lyrics=lyr, exclude_styles=case.get("exclude", ""),
                              instrumental=case.get("instrumental", False), seed=case.get("seed"),
                              description=case.get("description", ""))
        clips = pipeline.run_op("generate", req, pipeline.new_clips(req.variations, "generate"))
        d = out / case["name"]
        d.mkdir(parents=True, exist_ok=True)
        reports = []
        for c in clips:
            if c.status != "complete":
                reports.append({"clip": c.id, "error": c.error})
                continue
            rep = compare(settings.workdir / c.id / "master.flac", case["reference"], lyr)
            reports.append({"clip": c.id, **rep})
        (d / "report.json").write_text(json.dumps(reports, indent=2))
        best = max((r.get("overall", 0) for r in reports), default=0)
        summary.append({"name": case["name"], "best_overall": best})
        print(json.dumps(summary[-1]))
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
