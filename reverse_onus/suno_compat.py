"""Accept request bodies shaped like the Suno web app's POST /api/generate/v2-web/.

Observed in a capture of the user's own session (docs/FINDINGS.md section 7):
  mv "chirp-hawk", generation_type "TEXT", title, tags, negative_tags, prompt (lyrics),
  make_instrumental, gpt_description_prompt (simple mode),
  task "extend" + continue_clip_id + continue_at (seconds),
  task "cover" + cover_clip_id,
  metadata.control_sliders {weirdness_constraint, style_weight, aug_creativity} on 0..1,
  metadata.create_mode "custom".
Second capture: simple mode is task "agentic_thinking" (mv "chirp-goose") with the description in
  gpt_description_prompt; stems are task "gen_stem" + continue_clip_id + stem_task "twelve".
Third capture: Replace Section is task "infill" + continue_clip_id + infill_start_s / infill_end_s,
  new section lyrics in metadata.infill_lyrics, 15 s context either side, 2 s crossfade margins.
  Model keys: chirp-hawk = v6 (custom, extend, cover, infill), chirp-goose = v6 simple mode.
Clips come back from /api/feed/v3 with id, status, title, model_name, major_model_version,
  audio_url/media_urls and a metadata block (to_suno_clip mirrors it).
Fields the clone has no use for (persona_id, artist_clip_id, anti-bot tokens, transaction ids,
lyrics_project_id, override_fields, images) are ignored.
"""
from __future__ import annotations

from .schemas import Clip, CoverRequest, ExtendRequest, GenerateRequest, ReplaceSectionRequest, StemsRequest


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
    if task == "infill":
        return "replace-section", ReplaceSectionRequest(
            clip_id=body["continue_clip_id"], start=body["infill_start_s"], end=body["infill_end_s"],
            lyrics=meta.get("infill_lyrics") or "", **common)
    if task == "gen_stem":
        return "stems", StemsRequest(clip_id=body["continue_clip_id"])
    if task == "agentic_thinking" and not body.get("gpt_description_prompt"):
        raise ValueError("simple mode needs gpt_description_prompt")
    if task and task != "agentic_thinking":
        raise ValueError(f"task '{task}' isn't supported yet (generate, simple, extend, cover, infill, gen_stem)")
    return "generate", GenerateRequest(title=title, lyrics=body.get("prompt") or "",
                                       description=body.get("gpt_description_prompt") or "",
                                       instrumental=bool(body.get("make_instrumental")), **common)


def to_suno_clip(clip: Clip, audio_url: str | None) -> dict:
    """A clip in the shape /api/feed/v3 returns (fields observed in the user's capture)."""
    m = clip.metadata
    # Suno: submitted -> queued -> streaming -> complete. The clone doesn't stream audio early.
    status = {"queued": "submitted", "running": "queued", "complete": "complete"}.get(clip.status, "error")
    parent = m.get("parent_id")
    return {
        "id": clip.id, "status": status, "title": clip.title, "audio_url": audio_url,
        "model_name": "reverse-onus", "major_model_version": (m.get("engine") or {}).get("engine", "reverse-onus")
        if isinstance(m.get("engine"), dict) else "reverse-onus",
        "created_at": clip.created_at, "error_message": clip.error,
        "metadata": {
            "type": "gen", "task": {"generate": None, "concat": "concat"}.get(clip.task, clip.task),
            "tags": m.get("style", ""), "negative_tags": m.get("exclude_styles", ""),
            "prompt": m.get("lyrics", ""), "gpt_description_prompt": m.get("description") or None,
            "duration": clip.duration, "has_vocal": not m.get("instrumental", False),
            "is_remix": clip.task in ("extend", "cover"),
            "continue_at": m.get("continue_at"),
            "cover_clip_id": parent if clip.task == "cover" else None,
            "edited_clip_id": parent if clip.task == "replace-section" else None,
            "history": [{"id": parent, "continue_at": m.get("continue_at")}] if clip.task == "extend" else None,
        },
    }
