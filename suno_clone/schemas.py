"""Request and clip models. Field names follow Suno's composer (Custom mode: Lyrics, Styles,
Exclude styles, Title, Instrumental, Weirdness, Style Influence, Duration; Simple mode:
song description). The raw web-app JSON keys are not public; docs/REA_CAPTURE.md shows how
to read them from your own session and add aliases here."""
from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import settings

VocalGender = Literal["male", "female"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SoundControls(_Base):
    style: str = Field("", max_length=settings.max_style_chars, alias="tags")
    exclude_styles: str = Field("", max_length=settings.max_exclude_chars, alias="negative_tags")
    vocal_gender: VocalGender | None = None
    weirdness: float = Field(0.5, ge=0, le=1)        # Suno slider: Safe (0) .. Chaos (1)
    style_influence: float = Field(0.5, ge=0, le=1)  # Suno slider: Loose (0) .. Strong (1)
    seed: int | None = None


class GenerateRequest(SoundControls):
    description: str = Field("", max_length=settings.max_description_chars, alias="gpt_description_prompt")
    lyrics: str = Field("", max_length=settings.max_lyrics_chars, alias="prompt")
    title: str = Field("", max_length=settings.max_title_chars)
    instrumental: bool = Field(False, alias="make_instrumental")
    duration: float | None = Field(None, ge=10, le=settings.max_seconds)
    variations: int = Field(default_factory=lambda: settings.variations, ge=1, le=4)

    @model_validator(mode="after")
    def _needs_input(self):
        if not (self.description.strip() or self.lyrics.strip() or self.style.strip()):
            raise ValueError("give a song description (simple mode) or lyrics and/or style (custom mode)")
        return self

    @property
    def simple(self) -> bool:
        return bool(self.description.strip()) and not self.lyrics.strip()


class ExtendRequest(SoundControls):
    clip_id: str = Field(alias="continue_clip_id")
    continue_at: float | None = Field(None, ge=0)     # seconds; default: end of the clip
    lyrics: str = Field("", max_length=settings.max_lyrics_chars, alias="prompt")
    title: str = Field("", max_length=settings.max_title_chars)
    duration: float = Field(60, ge=10, le=settings.max_seconds)  # length of the new part
    inherit_style: bool = True                         # empty style -> parent's style
    variations: int = Field(default_factory=lambda: settings.variations, ge=1, le=4)


class CoverRequest(SoundControls):
    clip_id: str | None = None
    audio_url: str | None = None       # http(s) URL or local path of your own audio
    lyrics: str | None = Field(None, max_length=settings.max_lyrics_chars)  # None -> keep parent's
    title: str = Field("", max_length=settings.max_title_chars)
    audio_influence: float = Field(0.5, ge=0, le=1)
    variations: int = Field(default_factory=lambda: settings.variations, ge=1, le=4)

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.clip_id) == bool(self.audio_url):
            raise ValueError("give exactly one of clip_id or audio_url")
        return self


class ReplaceSectionRequest(SoundControls):
    clip_id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    lyrics: str = Field("", max_length=settings.max_lyrics_chars)  # lyrics for the new section
    variations: int = Field(default_factory=lambda: settings.variations, ge=1, le=4)

    @model_validator(mode="after")
    def _range(self):
        if self.end - self.start < 2:
            raise ValueError("section must be at least 2 seconds long")
        return self


class StemsRequest(_Base):
    clip_id: str


class ConcatRequest(_Base):
    clip_id: str  # last clip of an extend chain ("Get whole song")


ClipStatus = Literal["queued", "running", "complete", "error", "cancelled"]


class Clip(BaseModel):
    id: str
    status: ClipStatus = "queued"
    title: str = ""
    task: str = "generate"
    audio_url: str | None = None
    duration: float | None = None
    created_at: float = Field(default_factory=time.time)
    error: str | None = None
    metadata: dict = Field(default_factory=dict)
