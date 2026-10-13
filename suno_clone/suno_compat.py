"""Accept request bodies shaped like the Suno web app's POST /api/generate/v2-web/.

Observed in a capture of the user's own session (docs/FINDINGS.md section 7):
  mv "chirp-hawk", generation_type "TEXT", title, tags, negative_tags, prompt (lyrics),
  make_instrumental, gpt_description_prompt (simple mode),
  task "extend" + continue_clip_id + continue_at (seconds),
  task "cover" + cover_clip_id,
  metadata.control_sliders {weirdness_constraint, style_weight, aug_creativity} on 0..1,
  metadata.create_mode "custom".
Fields the clone has no use for (persona_id, artist_clip_id, anti-bot tokens, transaction ids,
lyrics_project_id, override_fields, images) are ignored.
"""
from __future__ import annotations

from .schemas import CoverRequest, ExtendRequest, GenerateRequest


def from_suno_body(body: dict) -> tuple[str, object]:
    meta = body.get("metadata") or {}
    sliders = meta.get("control_sliders") or {}
    common = {
        "style": body.get("tags") or "",
        "exclude_styles": body.get("negative_tags") or "",
        "weirdness": sliders.get("weirdness_constraint", 0.5),
        "style_influence": sliders.get("style_weight", 0.5),
    }
    title = body.get("title") or ""
    task = (body.get("task") or "").lower()
    if task == "extend":
        return "extend", ExtendRequest(clip_id=body["continue_clip_id"], continue_at=body.get("continue_at"),
                                       lyrics=body.get("prompt") or "", title=title, **common)
    if task == "cover":
        return "cover", CoverRequest(clip_id=body["cover_clip_id"], title=title,
                                     lyrics=body.get("prompt") or None, **common)
    if task:
        raise ValueError(f"task '{task}' isn't supported yet (generate, extend, cover)")
    return "generate", GenerateRequest(title=title, lyrics=body.get("prompt") or "",
                                       description=body.get("gpt_description_prompt") or "",
                                       instrumental=bool(body.get("make_instrumental")), **common)
