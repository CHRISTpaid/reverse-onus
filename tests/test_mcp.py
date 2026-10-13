import asyncio

import pytest

from reverse_onus import mcp_server as M

LYR = "[Verse]\nhello there\n\n[Chorus]\nla la la\n"


def test_tools_end_to_end():
    r = M.create_song(lyrics=LYR, style="pop", duration_s=20, seed=4, wait_seconds=120)
    assert r["next"] is None and len(r["songs"]) == 2
    s = r["songs"][0]
    assert s["status"] == "complete" and s["file"].endswith(".mp3") and s["style"] == "pop"
    ext = M.extend_song(s["id"], lyrics="[Bridge]\nmore", new_part_s=10, takes=1, wait_seconds=120)["songs"][0]
    assert ext["status"] == "complete" and ext["parent_id"] == s["id"]
    whole = M.whole_song(ext["id"])["songs"][0]
    assert abs(whole["duration_s"] - 30) < 0.5
    assert M.check_lyrics(LYR)["sections"][1]["section"] == "Chorus"
    assert any(x["id"] == s["id"] for x in M.list_songs(50)["songs"])
    assert "error" in M.check_songs(["missing"], 0)


def test_server_registers_tools():
    pytest.importorskip("mcp")
    server = M.build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"create_song", "check_songs", "extend_song", "replace_section", "cover_song",
            "split_stems", "whole_song", "list_songs", "check_lyrics", "cancel_songs"} <= names
    create = next(t for t in tools if t.name == "create_song")
    schema = getattr(create, "input_schema", None) or getattr(create, "inputSchema")
    assert "lyrics" in schema["properties"]
