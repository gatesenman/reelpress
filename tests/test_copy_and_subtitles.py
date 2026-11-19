import json

import httpx

from reelpress.llm import LLMClient, extract_json, generate_copy, normalize_bundle
from reelpress.subtitles import (
    build_cues,
    cues_from_boundaries,
    escape_ass,
    split_caption_lines,
    to_seconds,
    write_ass,
    write_srt,
)


def test_extract_json_from_fence():
    raw = """```json
{"title": "早安", "script": "你好。"}
```"""
    assert extract_json(raw)["title"] == "早安"


def test_normalize_keeps_user_script():
    bundle = normalize_bundle(
        {
            "title": "标题",
            "description": "简介",
            "hashtags": ["城市", "#清晨"],
            "script": "模型改写了",
            "search_terms": "city street, coffee",
        },
        "清晨",
        "用户原文。",
    )
    assert bundle.script == "用户原文。"
    assert bundle.hashtags[0] == "#城市"
    assert "city" in bundle.search_terms[0]


def test_llm_client_and_locked_script(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == settings.llm_model
        assert request.headers["authorization"] == "Bearer test-key"
        assert "用户原文" in body["messages"][1]["content"]
        payload = {
            "title": "街灯",
            "description": "一段很短的简介",
            "hashtags": ["#城市", "#步行"],
            "script": "不应被采用",
            "search_terms": ["city night", "bakery"],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]})

    settings.llm_api_key = "test-key"
    settings.llm_base_url = "https://llm.example/v1"
    client = LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model, client=httpx.Client(transport=httpx.MockTransport(handler)))
    bundle = generate_copy(settings, "街灯", "用户原文", "9:16", client=client)
    assert bundle.script == "用户原文"
    assert bundle.title == "街灯"
    assert bundle.search_terms == ["city night", "bakery"]


def test_offline_without_key_requires_script(settings):
    from reelpress.errors import ReelPressError

    try:
        generate_copy(settings, "主题", "", "9:16")
        raised = False
    except ReelPressError:
        raised = True
    assert raised
    demo = generate_copy(settings, "清晨", "", "9:16", mock=True)
    assert "街道" in demo.script


def test_caption_split_and_ticks(tmp_path):
    lines = split_caption_lines("清晨的街道还没完全醒来。面包店刚打开灯，空气里有麦香。")
    assert lines
    assert all(len(line) <= 16 for line in lines)
    assert to_seconds(15_000_000) == 1.5
    cues = cues_from_boundaries(
        [
            {"text": "清晨的街道", "offset": 0, "duration": 5_000_000},
            {"text": "还没醒来。", "offset": 5_000_000, "duration": 5_000_000},
            {"text": "面包店开灯", "offset": 10_000_000, "duration": 4_000_000},
        ]
    )
    assert cues[0].start == 0
    assert cues[-1].end > cues[0].end
    timed = build_cues("短句。另一句。", 2.0)
    srt = tmp_path / "a.srt"
    ass = tmp_path / "a.ass"
    write_srt(timed, srt)
    write_ass(timed, ass, 320, 568)
    assert "-->" in srt.read_text(encoding="utf-8")
    assert "Dialogue:" in ass.read_text(encoding="utf-8")
    assert escape_ass("a{b}") == r"a\{b\}"
