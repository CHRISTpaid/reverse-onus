import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from suno_clone import audio, pipeline
from suno_clone.config import settings
from suno_clone.eval.compare import compare
from suno_clone.eval.metrics import features, wer
from suno_clone.schemas import (ConcatRequest, CoverRequest, ExtendRequest, GenerateRequest,
                                ReplaceSectionRequest, StemsRequest)

LYR = "[Verse]\nhello there\nhow are you\n\n[Chorus]\nla la la\n"


def _gen(**kw):
    req = GenerateRequest(**{"style": "pop", "lyrics": LYR, "seed": 1, "duration": 40, **kw})
    return pipeline.run_op("generate", req, pipeline.new_clips(req.variations, "generate"))


def test_generate_two_variations():
    clips = _gen()
    assert len(clips) == 2 and all(c.status == "complete" for c in clips)
    assert all(abs(c.duration - 40) < 0.2 for c in clips)
    a, b = (audio.load(settings.workdir / c.id / "master.flac") for c in clips)
    assert not np.allclose(a, b)  # different seeds
    assert (settings.workdir / clips[0].id / f"{clips[0].id}.mp3").exists()
    assert (settings.workdir / clips[0].id / "debug.json").exists()
    assert clips[0].title == "hello there" and clips[0].metadata["seed"] == 1


def test_simple_mode_and_instrumental():
    c = pipeline.run_op("generate", GenerateRequest(description="song about rain", seed=3, duration=20),
                        pipeline.new_clips(1, "generate"))[0]
    assert c.status == "complete" and "[Verse]" in c.metadata["lyrics"]
    c = pipeline.run_op("generate", GenerateRequest(style="ambient", instrumental=True, duration=15, variations=1),
                        pipeline.new_clips(1, "generate"))[0]
    assert c.metadata["instrumental"] is True


def test_extend_and_whole_song():
    root = _gen(variations=1)[0]
    ext = pipeline.run_op("extend", ExtendRequest(clip_id=root.id, continue_at=30, duration=20, lyrics="[Bridge]\nnew"),
                          pipeline.new_clips(1, "extend"))[0]
    assert ext.status == "complete", ext.error
    assert abs(ext.duration - 20) < 0.2 and ext.metadata["parent_id"] == root.id
    assert ext.metadata["style"] == "pop"  # inherited
    ext2 = pipeline.run_op("extend", ExtendRequest(clip_id=ext.id, duration=15), pipeline.new_clips(1, "extend"))[0]
    whole = pipeline.concat(ConcatRequest(clip_id=ext2.id), pipeline.new_clips(1, "concat")[0])
    assert abs(whole.duration - (30 + 20 + 15)) < 0.3
    assert whole.metadata["parts"] == [root.id, ext.id, ext2.id]


def test_replace_section_keeps_the_rest():
    root = _gen(variations=1)[0]
    new = pipeline.run_op("replace-section", ReplaceSectionRequest(clip_id=root.id, start=10, end=20, lyrics="x"),
                          pipeline.new_clips(1, "replace-section"))[0]
    a = audio.load(settings.workdir / root.id / "master.flac")
    b = audio.load(settings.workdir / new.id / "master.flac")
    assert len(a) == len(b)
    s, e = audio.idx(10), audio.idx(20)
    assert np.abs(a[: s - audio.idx(0.2)] - b[: s - audio.idx(0.2)]).max() < 1e-3
    assert np.abs(a[e + audio.idx(0.2):] - b[e + audio.idx(0.2):]).max() < 1e-3
    assert np.abs(a[s + audio.idx(1): e - audio.idx(1)] - b[s + audio.idx(1): e - audio.idx(1)]).max() > 0.01


def test_cover_and_stems(tmp_path):
    root = _gen(variations=1)[0]
    cov = pipeline.run_op("cover", CoverRequest(clip_id=root.id, style="jazz", variations=1),
                          pipeline.new_clips(1, "cover"))[0]
    assert cov.status == "complete" and cov.metadata["lyrics"] == LYR
    up = audio.save(np.zeros((48000 * 12, 2), np.float32), tmp_path / "mine.wav")
    cov2 = pipeline.run_op("cover", CoverRequest(audio_url=str(up), style="rock", variations=1),
                           pipeline.new_clips(1, "cover"))[0]
    assert cov2.status == "complete"
    v, i = pipeline.run_op("stems", StemsRequest(clip_id=root.id), pipeline.new_clips(2, "stems"))
    assert v.metadata["stem"] == "vocals" and i.metadata["stem"] == "instrumental"


def test_errors_land_on_clips():
    clips = pipeline.run_op("extend", ExtendRequest(clip_id="missing"), pipeline.new_clips(1, "extend"))
    assert clips[0].status == "error"


def test_metrics_tempo_key_and_wer(tmp_path):
    sr = 48000
    t = np.arange(sr * 20) / sr
    beat = 0.5  # 120 BPM clicks over a C major triad
    clicks = (np.exp(-((t % beat) / 0.01)) * np.sin(2 * np.pi * 1000 * t))
    chord = sum(np.sin(2 * np.pi * f * t) for f in (261.63, 329.63, 392.0)) * 0.1
    x = (0.5 * clicks + chord).astype(np.float32)
    p = audio.save(np.stack([x, x], 1), tmp_path / "c.wav")
    f = features(p)
    assert abs(f["tempo_bpm"] - 120) < 3
    assert f["key"] in ("C major", "A minor", "E minor")
    rep = compare(p, p)
    assert rep["overall"] > 0.95
    assert wer("we rise we rise", "we rise we rice") == 0.25


@pytest.fixture(scope="module")
def client():
    from suno_clone.server import app
    return TestClient(app)


def _wait(client, ids, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        clips = client.get("/api/feed", params={"ids": ",".join(ids)}).json()["clips"]
        if all(c["status"] in ("complete", "error", "cancelled") for c in clips):
            return clips
        time.sleep(0.2)
    raise AssertionError("timed out")


def test_server_flow(client):
    r = client.post("/api/generate", json={"tags": "pop", "prompt": LYR, "seed": 5, "duration": 30},
                    headers={"Idempotency-Key": "k1"})
    assert r.status_code == 202
    ids = [c["id"] for c in r.json()["clips"]]
    assert len(ids) == 2
    again = client.post("/api/generate", json={"tags": "pop", "prompt": LYR, "seed": 5, "duration": 30},
                        headers={"Idempotency-Key": "k1"})
    assert [c["id"] for c in again.json()["clips"]] == ids
    assert client.post("/api/generate", json={"tags": "rock", "prompt": LYR},
                       headers={"Idempotency-Key": "k1"}).status_code == 409
    clips = _wait(client, ids)
    assert all(c["status"] == "complete" for c in clips)
    audio_r = client.get(clips[0]["audio_url"].replace("http://testserver", ""))
    assert audio_r.status_code == 200 and len(audio_r.content) > 1000
    r = client.post("/api/extend", json={"continue_clip_id": ids[0], "continue_at": 20, "duration": 15})
    ext = _wait(client, [c["id"] for c in r.json()["clips"]])
    assert ext[0]["status"] == "complete"
    whole = client.post("/api/concat", json={"clip_id": ext[0]["id"]}).json()
    assert abs(whole["duration"] - 35) < 0.3
    assert client.post("/api/extend", json={"continue_clip_id": "nope"}).status_code == 404
    assert client.post("/api/generate", json={"tags": "x" * 1001}).status_code == 422
    parsed = client.post("/api/lyrics/parse", json={"lyrics": LYR}).json()
    assert [s["kind"] for s in parsed["sections"]] == ["verse", "chorus"]
    assert client.get("/health").json()["backend"] == "mock"


def test_suno_shaped_bodies(client):
    from suno_clone.suno_compat import from_suno_body
    body = {"mv": "chirp-hawk", "generation_type": "TEXT", "title": "t", "tags": "pop", "negative_tags": "rock n roll",
            "prompt": LYR, "make_instrumental": False, "persona_id": None, "token": "x",
            "metadata": {"create_mode": "custom",
                         "control_sliders": {"weirdness_constraint": 0.23, "style_weight": 0.64, "aug_creativity": 1}}}
    op, req = from_suno_body(body)
    assert op == "generate" and req.weirdness == 0.23 and req.style_influence == 0.64
    assert req.exclude_styles == "rock n roll" and req.lyrics == LYR
    op, req = from_suno_body({"task": "extend", "continue_clip_id": "c1", "continue_at": 131, "prompt": "", "tags": "pop"})
    assert op == "extend" and req.clip_id == "c1" and req.continue_at == 131
    op, req = from_suno_body({"task": "cover", "cover_clip_id": "c2", "tags": "jazz"})
    assert op == "cover" and req.clip_id == "c2"
    r = client.post("/api/generate/v2-web/", json={**body, "metadata": {**body["metadata"]}, "duration": None})
    assert r.status_code == 202 and len(r.json()["clips"]) == 2
    assert client.post("/api/generate/v2-web/", json={"task": "infill"}).status_code == 422
    assert client.post("/api/generate/v2-web/", json={"task": "extend", "continue_clip_id": "nope"}).status_code == 404


def test_suno_simple_stems_and_feed_shape(client):
    from suno_clone.suno_compat import from_suno_body
    op, req = from_suno_body({"task": "agentic_thinking", "mv": "chirp-goose", "prompt": "",
                              "gpt_description_prompt": "a song about rain",
                              "metadata": {"create_mode": "simple", "lyrics_model": "default"}})
    assert op == "generate" and req.simple
    op, req = from_suno_body({"task": "gen_stem", "continue_clip_id": "c1", "stem_task": "twelve"})
    assert op == "stems" and req.clip_id == "c1"
    r = client.post("/api/generate/v2-web/", json={"tags": "pop", "prompt": LYR})
    ids = [c["id"] for c in r.json()["clips"]]
    _wait(client, ids)
    feed = client.get("/api/feed/v3", params={"ids": ",".join(ids)}).json()["clips"]
    assert feed[0]["status"] == "complete" and feed[0]["metadata"]["tags"] == "pop"
    assert feed[0]["metadata"]["prompt"] == LYR and feed[0]["audio_url"].endswith(".mp3")
