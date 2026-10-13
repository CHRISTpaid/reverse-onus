"""ACE-Step 1.5 (MIT) through its REST server.

  git clone https://github.com/ace-step/ACE-Step-1.5 && cd ACE-Step-1.5 && uv sync
  uv run acestep-api            # http://localhost:8001

API: POST /release_task -> {data:{task_id}}; POST /query_result {task_id_list:[id]} ->
data[i].status 0 running / 1 done / 2 failed, data[i].result = JSON string listing
{file:"/v1/audio?path=..."}; GET /v1/audio?path=... (docs/en/API.md in the ACE-Step repo).

Suno controls map to ACE-Step like this (Inferred, tune with the A/B harness):
  Styles            -> prompt (caption, 512 chars max)
  Exclude styles    -> lm_negative_prompt (the LM's CFG negative)
  Weirdness 0..1    -> lm_temperature 0.55..1.15 (0.85 default at the centre)
  Style Influence   -> lm_cfg_scale 1.5..3.5 and guidance_scale 4..10 (base models only);
                       strong influence (>=0.75) also stops the LM rewriting the caption
  Two songs         -> batch_size 2
  Simple mode       -> sample_mode + sample_query (the LM writes lyrics, style, metadata)
  Audio Influence   -> audio_cover_strength 0.2..1.0
  Extract stems     -> task_type extract (needs a base DiT model, set ACESTEP_BASE_MODEL)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from .. import lyrics as L
from ..config import settings
from .base import Backend, BackendError, Cancelled, EngineResult, EngineTask


def sliders(weirdness: float, style_influence: float) -> dict:
    return {
        "lm_temperature": round(0.55 + 0.6 * weirdness, 3),
        "lm_top_p": 0.9,
        "lm_cfg_scale": round(1.5 + 2.0 * style_influence, 3),
        "guidance_scale": round(4.0 + 6.0 * style_influence, 3),
        "use_cot_caption": style_influence < 0.75,
    }


_LANGUAGES = ("english", "spanish", "french", "german", "italian", "portuguese", "dutch", "russian", "polish",
              "turkish", "arabic", "hindi", "japanese", "korean", "chinese", "mandarin", "cantonese",
              "vietnamese", "thai", "indonesian", "swahili", "zulu", "shona", "yoruba", "latin")


def describe_query(description: str) -> str:
    """Simple mode ignores vocal_language and follows a language named in the description (seen on a
    live ACE-Step 1.5 run: an English description got Vietnamese lyrics). So an ASCII description that
    names no language gets ". English" appended."""
    d = description.strip()
    words = set(re.findall(r"[a-z]+", d.lower()))
    if d.isascii() and not words.intersection(_LANGUAGES):
        return d.rstrip(" .") + ". English"
    return d


def build_request(task: EngineTask) -> dict:
    """The /release_task body for a task (pure; unit tested)."""
    st = task.style
    body: dict = {
        "prompt": st.caption,
        "lyrics": "[Instrumental]" if st.instrumental else L.render_tagged(task.song),
        "batch_size": task.variations,
        "audio_format": "flac",
        **sliders(st.weirdness, st.style_influence),
    }
    if st.negative:
        body["lm_negative_prompt"] = st.negative
    if task.seed is not None:
        body["use_random_seed"] = False
        body["seed"] = ",".join(str(task.seed + i) for i in range(task.variations))
    if settings.acestep_model:
        body["model"] = settings.acestep_model
    if task.kind == "generate":
        body["task_type"] = "text2music"
        body["thinking"] = settings.acestep_thinking
        if task.duration:
            body["audio_duration"] = round(task.duration, 2)
    elif task.kind == "describe":
        body.update(task_type="text2music", sample_mode=True, sample_query=describe_query(task.description),
                    thinking=True)
        body.pop("lyrics")
        if not st.caption:
            body.pop("prompt")
        if task.duration:
            body["audio_duration"] = round(task.duration, 2)
    elif task.kind == "repaint":
        body.update(task_type="repaint", repainting_start=round(task.start, 3),
                    repainting_end=round(task.end, 3) if task.end >= 0 else -1, chunk_mask_mode="explicit")
    elif task.kind == "cover":
        body.update(task_type="cover", audio_cover_strength=round(task.cover_strength, 3))
    elif task.kind == "stems":
        body.update(task_type="extract", instruction=f"Extract the {task.stem} track from the audio:",
                    batch_size=1)
        body.pop("lyrics")
        if settings.acestep_base_model:
            body["model"] = settings.acestep_base_model
    else:
        raise BackendError(f"unsupported task {task.kind}")
    return body


class AceStepBackend(Backend):
    name = "acestep"
    capabilities = frozenset({"generate", "describe", "repaint", "cover", "stems"})

    def __init__(self) -> None:
        headers = {"Authorization": f"Bearer {settings.acestep_api_key}"} if settings.acestep_api_key else {}
        self.http = httpx.Client(base_url=settings.acestep_url, headers=headers, timeout=120)

    def _submit(self, body: dict, src: Path | None) -> str:
        try:
            if src is not None:
                form = {k: (json.dumps(v) if isinstance(v, (bool, dict, list)) else str(v)) for k, v in body.items()}
                with open(src, "rb") as f:
                    r = self.http.post("/release_task", data=form, files={"src_audio": (src.name, f)})
            else:
                r = self.http.post("/release_task", json=body)
        except httpx.ConnectError:
            raise BackendError(f"Can't reach ACE-Step at {settings.acestep_url}. Start its API server first "
                               "(start_api_server.bat on Windows, or `uv run acestep-api`) and wait until it "
                               "has finished loading.") from None
        r.raise_for_status()
        doc = r.json()
        if doc.get("code", 200) != 200 or not (doc.get("data") or {}).get("task_id"):
            raise BackendError(f"ACE-Step refused the task: {doc.get('error') or doc}")
        return doc["data"]["task_id"]

    def _wait(self, task_id: str, task: EngineTask) -> list[dict]:
        deadline = time.monotonic() + settings.timeout_seconds
        while time.monotonic() < deadline:
            if task.cancel.is_set():
                raise Cancelled("cancelled")
            r = self.http.post("/query_result", json={"task_id_list": [task_id]})
            r.raise_for_status()
            item = (r.json().get("data") or [{}])[0]
            st = item.get("status")
            if st == 1:
                res = item.get("result")
                return json.loads(res) if isinstance(res, str) else (res or [])
            if st == 2:
                raise BackendError(f"ACE-Step task failed: {item.get('result') or item}")
            task.cancel.wait(settings.poll_interval)
        raise BackendError("ACE-Step timed out")

    def run(self, task: EngineTask) -> EngineResult:
        self.require(task.kind)
        task.out_dir.mkdir(parents=True, exist_ok=True)
        body = build_request(task)
        task.log.append("acestep request: " + json.dumps(body)[:2000])
        tid = self._submit(body, task.src_audio if task.kind in ("repaint", "cover", "stems") else None)
        items = self._wait(tid, task)
        files = []
        for i, it in enumerate(items):
            url = it.get("file")
            if not url:
                continue
            dest = task.out_dir / f"acestep-{task.kind}-{i}.flac"
            with self.http.stream("GET", url) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            files.append(dest)
        if not files:
            raise BackendError("ACE-Step finished without audio")
        first = items[0]
        return EngineResult(files=files, lyrics=first.get("lyrics") if task.kind == "describe" else None,
                            caption=first.get("prompt") if task.kind == "describe" else None,
                            meta={"engine": "acestep", "task_id": tid, "metas": first.get("metas"),
                                  "dit_model": first.get("dit_model"), "lm_model": first.get("lm_model"),
                                  "seeds": first.get("seed_value")})
