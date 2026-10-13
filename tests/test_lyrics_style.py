import pytest
from pydantic import ValidationError

from reverse_onus import lyrics as L
from reverse_onus.backends.acestep import build_request, sliders
from reverse_onus.backends.base import EngineTask
from reverse_onus.schemas import CoverRequest, GenerateRequest, ReplaceSectionRequest
from reverse_onus.style import compile_style

SONG = """[Intro: soft piano]

[Verse 1]
Walking down the empty road
(ooh, ooh)
Carrying a heavy load

[Female Vocal]
[Pre-Chorus]
Something's gonna change

[Chorus - powerful, gang vocals]
We rise, we rise
Into the open skies

[Guitar Solo]

[Outro]
[End]
this line is never sung
"""


def test_parse_sections_and_descriptors():
    s = L.parse(SONG)
    kinds = [x.kind for x in s.sections]
    assert kinds == ["intro", "verse", "pre-chorus", "chorus", "solo", "outro"]
    assert s.sections[0].descriptors == ["soft piano"] and s.sections[0].instrumental
    assert s.sections[1].number == 1 and "(ooh, ooh)" in s.sections[1].lines
    assert s.sections[2].descriptors == ["female vocals"]  # voice tag before a section's lines
    assert s.sections[3].descriptors == ["powerful", "gang vocals"]
    assert s.sections[4].descriptors == ["guitar solo"]
    assert s.ended and "never sung" not in L.render_tagged(s)


def test_render_formats():
    s = L.parse(SONG)
    ace = L.render_tagged(s)
    assert ace.startswith("[Intro]\n\n[Verse]\nWalking")
    yue = L.render_tagged(s, lowercase=True, keep_instrumental_sections=False)
    assert yue.startswith("[verse]") and "[solo]" not in yue
    assert L.plain_text(s).startswith("Walking down the empty road Carrying")


def test_untagged_lyrics_and_estimate():
    s = L.parse("line one\nline two\n")
    assert s.sections[0].kind == "body" and L.render_tagged(s).startswith("[Verse]")
    assert 30 <= L.estimate_seconds(s) <= 480
    assert L.estimate_seconds(L.parse("")) == 120.0
    assert L.parse("[Instrumental]").is_instrumental


def test_style_compile():
    s = L.parse(SONG)
    spec = compile_style("indie pop, dreamy, drums, Indie Pop", "drums, autotune", vocal_gender="female", song=s)
    assert spec.tags[:2] == ["indie pop", "dreamy"]
    assert "drums" not in spec.tags and "dropped" in spec.notes[0]
    assert "female vocals" in spec.caption and "chorus 1" not in spec.caption
    assert "chorus: powerful, gang vocals" in spec.caption
    assert spec.negative == "drums, autotune"
    inst = compile_style("ambient", instrumental=True)
    assert inst.instrumental and "instrumental" in inst.tags and inst.negative == "vocals"
    long = compile_style(", ".join(f"tag{i:03d}" for i in range(200)))
    assert len(long.caption) <= 512 and long.notes


def test_limits_match_suno():
    with pytest.raises(ValidationError):
        GenerateRequest(style="x" * 1001)
    with pytest.raises(ValidationError):
        GenerateRequest(lyrics="x" * 5001)
    with pytest.raises(ValidationError):
        GenerateRequest()
    with pytest.raises(ValidationError):
        GenerateRequest(style="pop", weirdness=1.5)
    with pytest.raises(ValidationError):
        CoverRequest(style="jazz")
    with pytest.raises(ValidationError):
        ReplaceSectionRequest(clip_id="a", start=10, end=11)
    r = GenerateRequest.model_validate({"tags": "pop", "prompt": "[Verse]\nhi", "make_instrumental": False})
    assert r.style == "pop" and r.lyrics.startswith("[Verse]") and r.variations == 2
    assert GenerateRequest(description="a song about rain").simple


def test_acestep_request_mapping(tmp_path):
    s = L.parse(SONG)
    spec = compile_style("pop", "metal", song=s, weirdness=0.5, style_influence=0.5)
    t = EngineTask(kind="generate", style=spec, song=s, out_dir=tmp_path, seed=7, variations=2, duration=95)
    b = build_request(t)
    assert b["task_type"] == "text2music" and b["batch_size"] == 2 and b["seed"] == "7,8"
    assert b["lm_temperature"] == 0.85 and b["lm_cfg_scale"] == 2.5 and b["lm_negative_prompt"] == "metal"
    assert b["audio_duration"] == 95 and b["lyrics"].startswith("[Intro]")
    t.kind, t.start, t.end = "repaint", 30.0, -1
    b = build_request(t)
    assert b["task_type"] == "repaint" and b["repainting_end"] == -1 and b["chunk_mask_mode"] == "explicit"
    t.kind, t.description = "describe", "lofi song about tea"
    b = build_request(t)
    assert b["sample_mode"] and b["sample_query"] == "lofi song about tea. English" and "lyrics" not in b
    t.kind = "stems"
    b = build_request(t)
    assert b["task_type"] == "extract" and "vocals" in b["instruction"]
    assert sliders(0, 1)["use_cot_caption"] is False and sliders(1, 0)["lm_temperature"] == 1.15


def test_acestep_down_gives_a_clear_error(monkeypatch):
    from reverse_onus.backends.acestep import AceStepBackend
    from reverse_onus.backends.base import BackendError
    from reverse_onus.config import settings
    monkeypatch.setattr(settings, "acestep_url", "http://127.0.0.1:9")  # nothing listens on the discard port
    with pytest.raises(BackendError, match="Start its API server"):
        AceStepBackend()._submit({"prompt": "pop"}, None)


def test_simple_mode_language():
    from reverse_onus.backends.acestep import describe_query
    assert describe_query("a sad country song about a lost dog.") == "a sad country song about a lost dog. English"
    assert describe_query("a Spanish love song") == "a Spanish love song"
    assert describe_query("une chanson d'été") == "une chanson d'été"
