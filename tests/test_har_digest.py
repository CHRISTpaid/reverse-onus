import json
import subprocess
import sys
from pathlib import Path


def test_har_digest_prints_generation_fields(tmp_path):
    rea = {"normalized_result": {"records": [
        {"ordinal": 1, "reported": {"request": {"method": "GET", "url": "https://cdn.example.com/logo.png"},
                                    "response": {"status": 200}}},
        {"ordinal": 2, "reported": {
            "request": {"method": "POST", "url": "https://studio-api.example.com/api/generate/v2/",
                        "postData": {"text": json.dumps({"mv": "model-x", "tags": "pop", "prompt": "[Verse]\nhi",
                                                         "make_instrumental": False, "weirdness": 0.7})}},
            "response": {"status": 200, "content": {"text": json.dumps({"clips": [{"id": "c1", "status": "submitted"}]})}}}},
    ]}}
    p = tmp_path / "rea.json"
    p.write_text(json.dumps(rea))
    script = Path(__file__).parent.parent / "scripts" / "har_digest.py"
    out = subprocess.run([sys.executable, str(script), str(p)], capture_output=True, text=True, check=True).stdout
    assert "#2 POST studio-api.example.com/api/generate/v2/" in out
    assert 'request.mv = "model-x"' in out and "request.weirdness = 0.7" in out
    assert "logo.png" not in out and "mv: \"model-x\"" in out
