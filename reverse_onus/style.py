"""Suno style controls -> one engine-neutral spec.

Suno: Styles (free text, up to 1,000 chars), Exclude styles, vocal gender, Weirdness and
Style Influence sliders, Instrumental toggle. Engines take a caption (ACE-Step: 512 chars),
a negative prompt and sampling knobs. The slider mappings below are Inferred (Suno shows no
numbers); tune them with the A/B harness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lyrics as L


@dataclass
class StyleSpec:
    caption: str
    negative: str
    tags: list[str]
    excluded: list[str]
    weirdness: float
    style_influence: float
    instrumental: bool
    notes: list[str] = field(default_factory=list)


def split_tags(text: str) -> list[str]:
    parts = re.split(r"[,\n;|]+", text or "")
    seen, out = set(), []
    for p in parts:
        t = " ".join(p.split()).strip(" .")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def _fit(items: list[str], limit: int) -> str:
    out = ""
    for it in items:
        cand = f"{out}, {it}" if out else it
        if len(cand) > limit:
            break
        out = cand
    return out


def compile_style(style: str, exclude: str = "", *, vocal_gender: str | None = None,
                  instrumental: bool = False, song: L.Song | None = None, weirdness: float = 0.5,
                  style_influence: float = 0.5, caption_limit: int = 512) -> StyleSpec:
    tags = split_tags(style)
    excluded = split_tags(exclude)
    notes: list[str] = []
    if song is not None and song.is_instrumental and song.sections:
        instrumental = True
    if instrumental:
        if not any("instrumental" in t.lower() for t in tags):
            tags.append("instrumental")
        if not any("vocal" in t.lower() for t in excluded):
            excluded.append("vocals")
    else:
        voice = []
        if vocal_gender:
            voice.append(f"{vocal_gender} vocals")
        if song is not None:
            voice += song.voice
        for v in voice:
            if not any(v.split()[0] in t.lower() for t in tags):
                tags.append(v)
    # Excluded terms must not also be requested.
    ex_low = [e.lower() for e in excluded]
    kept = [t for t in tags if t.lower() not in ex_low]
    if len(kept) < len(tags):
        notes.append("dropped style tags that were also excluded")
    tags = kept
    extra = L.section_notes(song) if song is not None else []
    caption = _fit(tags + extra, caption_limit)
    if len(caption) < len(", ".join(tags + extra)):
        notes.append(f"caption trimmed to {caption_limit} chars for the engine")
    return StyleSpec(caption=caption, negative=", ".join(excluded), tags=tags, excluded=excluded,
                     weirdness=weirdness, style_influence=style_influence, instrumental=instrumental,
                     notes=notes)
