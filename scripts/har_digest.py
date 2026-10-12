"""Summarise Suno web-app traffic from REA's HAR inspection output.

  npx -y rea-agents@latest inspect-web-network-capture /abs/suno.har har --json > rea.json
  python scripts/har_digest.py rea.json

For every request whose URL or body looks like song generation, editing or playback, prints
the method, path, status and the body fields that name a model, task, style, slider, length,
parent clip or audio format. Those settle the open questions in docs/FINDINGS.md section 6.
REA already redacts credentials; this script never prints headers or cookies.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse

HINT = re.compile(r"suno|chirp|generate|clip|lyric|extend|continue|cover|remaster|persona|voice|"
                  r"stem|infill|replace|concat|upload|feed|audio_url|\bmv\b", re.I)
INTERESTING = re.compile(r"^(mv|model.*|task|type|tags|negative_tags|prompt|gpt_description_prompt|title|"
                         r"make_instrumental|instrumental|continue_.*|cover_.*|.*clip_id|persona.*|voice.*|"
                         r".*weird.*|.*influence.*|.*weight.*|duration|.*seconds|.*_s|infill_.*|start.*|end.*|"
                         r"audio_url|video_url|image_url|stream.*|format|bitrate|sample_rate|status|"
                         r"major_model_version|model_name|metadata|history|edit.*|stem.*|batch.*|seed)$", re.I)


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def body_json(text):
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def main(path: str) -> None:
    doc = json.load(open(path))
    records = (doc.get("normalized_result") or doc).get("records", [])
    seen_values: dict[str, set] = {}
    for r in records:
        rep = r.get("reported", {})
        req, res = rep.get("request", {}), rep.get("response", {})
        url = req.get("url", "")
        req_body = body_json((req.get("postData") or {}).get("text"))
        res_body = body_json((res.get("content") or {}).get("text"))
        if not HINT.search(url + json.dumps(req_body)[:4000]):
            continue
        u = urlparse(url)
        print(f"\n#{r.get('ordinal')} {req.get('method')} {u.netloc}{u.path} -> {res.get('status')}")
        for label, body in (("request", req_body), ("response", res_body)):
            if body is None:
                continue
            for k, v in walk(body):
                leaf = re.sub(r"\[\d+\]", "", k.rsplit(".", 1)[-1])
                if INTERESTING.match(leaf):
                    sv = json.dumps(v)
                    print(f"  {label}.{k} = {sv[:160]}{'...' if len(sv) > 160 else ''}")
                    if leaf in ("mv", "model", "model_name", "major_model_version", "task", "type"):
                        seen_values.setdefault(leaf, set()).add(sv[:80])
    if seen_values:
        print("\nModel/task values seen:")
        for k, vs in sorted(seen_values.items()):
            print(f"  {k}: {', '.join(sorted(vs))}")


if __name__ == "__main__":
    main(sys.argv[1])
