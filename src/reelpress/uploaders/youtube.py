"""YouTube Data API v3 resumable upload with OAuth installed-app flow.

Videos scheduled for later are uploaded as private with status.publishAt,
which is what the official API requires. Unverified Google Cloud projects
may still force uploads to stay private until the app passes audit.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.models import UploadRequest, UploadResult
from reelpress.uploaders.base import safe_account

YOUTUBE_LABEL = "YouTube"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def token_path(settings: Settings, account: str) -> Path:
    return settings.token_dir / f"youtube_{safe_account(account)}.json"


def build_auth_url(settings: Settings, state: str) -> str:
    if not settings.youtube_client_id:
        raise ReelPressError("请先在设置里填写 YouTube OAuth 客户端 ID。")
    query = urlencode(
        {
            "client_id": settings.youtube_client_id,
            "redirect_uri": settings.youtube_redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def _write_token(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def exchange_code(settings: Settings, code: str, *, client: httpx.Client | None = None, account: str = "default") -> dict:
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        raise ReelPressError("YouTube OAuth 客户端 ID 或密钥未配置。")
    http, owns = _http(client)
    try:
        response = http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "redirect_uri": settings.youtube_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    finally:
        if owns:
            http.close()
    if response.status_code >= 400:
        raise ReelPressError(f"YouTube 授权码交换失败：{response.text[:240]}")
    token = response.json()
    saved = {
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": time.time() + int(token.get("expires_in") or 3600),
        "account": account,
    }
    _write_token(token_path(settings, account), saved)
    return saved


def refresh_access_token(settings: Settings, account: str, *, client: httpx.Client | None = None) -> str:
    path = token_path(settings, account)
    if not path.exists():
        raise ReelPressError("YouTube 尚未授权。请先完成 OAuth 登录。")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved.get("access_token") and float(saved.get("expires_at") or 0) > time.time() + 60:
        return str(saved["access_token"])
    if not saved.get("refresh_token"):
        raise ReelPressError("YouTube 刷新令牌缺失，请重新授权。")
    http, owns = _http(client)
    try:
        response = http.post(
            TOKEN_URL,
            data={
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "refresh_token": saved["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
    finally:
        if owns:
            http.close()
    if response.status_code >= 400:
        raise ReelPressError(f"YouTube 刷新令牌失败：{response.text[:240]}")
    token = response.json()
    saved["access_token"] = token.get("access_token", "")
    saved["expires_at"] = time.time() + int(token.get("expires_in") or 3600)
    if token.get("refresh_token"):
        saved["refresh_token"] = token["refresh_token"]
    _write_token(path, saved)
    return str(saved["access_token"])


def _tags(hashtags: list[str]) -> list[str]:
    tags = []
    for tag in hashtags:
        cleaned = tag.lstrip("#").strip()
        if cleaned:
            tags.append(cleaned[:30])
    return tags[:15]


def upload_video(
    settings: Settings,
    request: UploadRequest,
    *,
    client: httpx.Client | None = None,
) -> UploadResult:
    access = refresh_access_token(settings, request.account, client=client)
    video = Path(request.video_path)
    if not video.exists():
        raise ReelPressError("成片不存在，无法上传到 YouTube。")
    privacy = "private" if request.schedule_at else "public"
    status: dict = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if request.schedule_at:
        status["publishAt"] = request.schedule_at
    metadata = {
        "snippet": {
            "title": request.title[:100] or "Untitled",
            "description": _description(request),
            "tags": _tags(request.hashtags),
            "categoryId": "22",
        },
        "status": status,
    }
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(video.stat().st_size),
    }
    http, owns = _http(client, timeout=300)
    try:
        start = http.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            json=metadata,
        )
        if start.status_code >= 400:
            raise ReelPressError(f"YouTube 申请上传地址失败：{start.text[:300]}")
        location = start.headers.get("Location") or start.headers.get("location")
        if not location:
            raise ReelPressError("YouTube 没有返回断点续传地址。")
        with video.open("rb") as handle:
            put = http.put(
                location,
                content=handle.read(),
                headers={
                    "Authorization": f"Bearer {access}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(video.stat().st_size),
                },
            )
    finally:
        if owns:
            http.close()
    if put.status_code >= 400:
        raise ReelPressError(f"YouTube 上传失败：{put.text[:300]}")
    video_id = str(put.json().get("id") or "")
    url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
    message = "已上传到 YouTube。"
    if request.schedule_at:
        message = "已按定时设置上传为私享，到点后由 YouTube 公开。"
    message += " 未通过 Google 审核的 API 项目，视频可能会被强制为私享。"
    return UploadResult(platform="youtube", success=True, url=url, message=message)


def _description(request: UploadRequest) -> str:
    tags = " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in request.hashtags)
    return f"{request.description.strip()}\n\n{tags}".strip()[:5000]


def _http(client: httpx.Client | None, timeout: float = 60) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(timeout=timeout), True


class YouTubeUploader:
    name = "youtube"
    label = YOUTUBE_LABEL
    method = "youtube-data-api"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    def cookie_file(self, settings: Settings, account: str) -> Path:
        return token_path(settings, account)

    def check(self, settings: Settings, account: str, *, live: bool = False) -> bool:
        del live
        path = token_path(settings, account)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        return bool(data.get("refresh_token") or data.get("access_token"))

    def login(self, settings: Settings, account: str, **kwargs):
        del account, kwargs
        raise ReelPressError("YouTube 使用 OAuth，不走二维码。请在网页里点击「前往 Google 授权」，或打开授权链接。")

    def upload(self, settings: Settings, request: UploadRequest) -> UploadResult:
        return upload_video(settings, request, client=self.client)
