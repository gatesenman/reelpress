import json
import time
from pathlib import Path

import httpx

from reelpress.models import UploadRequest
from reelpress.uploaders.platforms import BrowserUploader, get_spec
from reelpress.uploaders.registry import uploader_names
from reelpress.uploaders.youtube import exchange_code, upload_video


class FakeSession:
    def __init__(self, logged_in: bool = False):
        self.cookies_list = (
            [{"name": "sessionid", "value": "session-value", "expires": -1}] if logged_in else []
        )
        self.filled: list[str] = []
        self.clicked = 0
        self.files = ""
        self.saved = ""
        self.shots = 0

    def goto(self, url: str) -> None:
        self.page_url = url

    def cookies(self) -> list[dict]:
        return self.cookies_list

    def screenshot(self) -> bytes:
        self.shots += 1
        self.cookies_list = [{"name": "sessionid", "value": "session-value", "expires": -1}]
        return b"\x89PNG\r\n\x1a\nfake"

    def save_storage(self, path: str) -> None:
        self.saved = path
        Path(path).write_text(
            json.dumps({"cookies": self.cookies_list, "origins": []}),
            encoding="utf-8",
        )

    def set_files(self, path: str) -> None:
        self.files = path

    def fill_any(self, selectors, text: str) -> bool:
        self.filled.append(text)
        return True

    def click_any(self, selectors, text_names=()) -> bool:
        self.clicked += 1
        return True

    def url(self) -> str:
        return getattr(self, "page_url", "")


def test_platform_registry_lists_expected_names():
    names = uploader_names()
    for required in ("youtube", "douyin", "kuaishou", "xiaohongshu", "bilibili"):
        assert required in names


def test_douyin_login_and_upload(settings, tmp_path):
    spec = get_spec("douyin")
    login_session = FakeSession()
    uploader = BrowserUploader(spec, session_factory=lambda _path: login_session)
    saved = uploader.login(settings, "shop", on_qr=lambda png: None)
    assert Path(saved).exists()
    assert login_session.shots >= 1
    assert uploader.check(settings, "shop") is True

    upload_session = FakeSession(logged_in=True)
    uploader.session_factory = lambda _path: upload_session
    video = tmp_path / "final.mp4"
    video.write_bytes(b"not-a-real-video")
    result = uploader.upload(
        settings,
        UploadRequest(
            video_path=str(video),
            title="十二点的便利店还亮着灯",
            description="夜路很短。",
            hashtags=["#城市", "夜"],
            account="shop",
        ),
    )
    assert result.success
    assert upload_session.files == str(video)
    assert any("夜路" in text for text in upload_session.filled)
    assert upload_session.clicked == 1


def test_expired_cookie_is_invalid(settings):
    spec = get_spec("bilibili")
    uploader = BrowserUploader(spec, session_factory=lambda _path: FakeSession())
    path = uploader.cookie_file(settings, "default")
    path.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "SESSDATA", "value": "old", "expires": time.time() - 100},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert uploader.check(settings, "default") is False


def test_youtube_oauth_and_scheduled_upload(settings, tmp_path):
    settings.youtube_client_id = "client"
    settings.youtube_client_secret = "secret"

    def token_handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "authorization_code" in body
        return httpx.Response(
            200,
            json={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
        )

    saved = exchange_code(
        settings,
        "code-123",
        client=httpx.Client(transport=httpx.MockTransport(token_handler)),
        account="main",
    )
    assert saved["refresh_token"] == "refresh"

    seen: dict = {}

    def upload_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["meta"] = json.loads(request.content)
            return httpx.Response(200, headers={"Location": "https://upload.example/session"}, json={})
        if request.method == "PUT":
            seen["size"] = len(request.content)
            return httpx.Response(200, json={"id": "vid123"})
        return httpx.Response(404)

    video = tmp_path / "final.mp4"
    video.write_bytes(b"0123456789")
    result = upload_video(
        settings,
        UploadRequest(
            video_path=str(video),
            title="Morning",
            description="A short walk.",
            hashtags=["#city"],
            account="main",
            schedule_at="2026-10-10T12:00:00+00:00",
        ),
        client=httpx.Client(transport=httpx.MockTransport(upload_handler)),
    )
    assert result.success
    assert result.url.endswith("vid123")
    assert seen["meta"]["status"]["privacyStatus"] == "private"
    assert seen["meta"]["status"]["publishAt"] == "2026-10-10T12:00:00+00:00"
    assert seen["meta"]["snippet"]["tags"] == ["city"]
    assert seen["size"] == 10
