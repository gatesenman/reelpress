import base64

import httpx

from reelpress.materials import collect_clips, search_ai_visual


def test_missing_stock_key_uses_placeholder(settings, tmp_path):
    warnings: list[str] = []
    clips = collect_clips(
        settings,
        ["city", "bread"],
        tmp_path / "clips",
        "9:16",
        clip_seconds=0.6,
        provider="pexels",
        warnings=warnings,
        count=2,
    )
    assert clips
    assert all(path.stat().st_size > 200 for path in clips)
    assert any("占位" in note or "未配置" in note for note in warnings)


def test_pexels_download_uses_mock_http(settings, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "api.pexels.com" in str(request.url):
            assert request.headers["authorization"] == "pexels-test"
            return httpx.Response(
                200,
                json={
                    "videos": [
                        {
                            "video_files": [
                                {
                                    "file_type": "video/mp4",
                                    "width": 1080,
                                    "height": 1920,
                                    "link": "https://cdn.example/a.mp4",
                                }
                            ]
                        }
                    ]
                },
            )
        if str(request.url).endswith(".mp4"):
            return httpx.Response(200, content=b"fake-mp4")
        return httpx.Response(404)

    settings.pexels_api_key = "pexels-test"
    client = httpx.Client(transport=httpx.MockTransport(handler))
    clips = collect_clips(
        settings,
        ["city night"],
        tmp_path / "clips",
        "9:16",
        provider="pexels",
        http=client,
        count=1,
    )
    assert clips[0].read_bytes() == b"fake-mp4"


def test_ai_hook_accepts_base64(settings):
    payload = base64.b64encode(b"video-bytes").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json_body(request)
        assert body["prompt"] == "rainy street"
        assert body["aspect"] == "9:16"
        assert request.headers["authorization"] == "Bearer ai-test"
        return httpx.Response(200, json={"b64": payload})

    settings.visual_ai_base_url = "https://visual.example"
    settings.visual_ai_api_key = "ai-test"
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = search_ai_visual(settings, "rainy street", "9:16", 3, client)
    assert result == b"video-bytes"


def json_body(request: httpx.Request):
    import json

    return json.loads(request.content)
