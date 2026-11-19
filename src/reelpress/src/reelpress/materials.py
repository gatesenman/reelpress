"""Stock footage and the optional AI visual hook.

Pexels and Pixabay are searched with the English terms the LLM produced.
When no key is configured, or a download fails, the pipeline renders
labeled placeholder clips so a video can still be composed.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.media import cjk_font_file, escape_drawtext, frame_size, run_ffmpeg

_COLORS = ["0x1c1915", "0x243044", "0x3d4f3a", "0x5c3d2e", "0x3a2a32", "0x2c3338"]


def _client(http: httpx.Client | None, timeout: float = 45) -> tuple[httpx.Client, bool]:
    if http is not None:
        return http, False
    return httpx.Client(timeout=timeout, follow_redirects=True), True


def render_placeholder(
    path: Path,
    label: str,
    width: int,
    height: int,
    duration: float,
    color: str,
    fps: int,
) -> None:
    font = cjk_font_file()
    font_opt = f"fontfile={font}:" if font else ""
    safe = escape_drawtext((label or "映流")[:18])
    brand = escape_drawtext("映流")
    draw = (
        f"drawtext={font_opt}text='{brand}':fontsize=28:fontcolor=0xE4D3B0:"
        f"x=48:y=56,"
        f"drawtext={font_opt}text='{safe}':fontsize=42:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2"
    )
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={width}x{height}:r={fps}:d={duration:.3f}",
            "-vf",
            draw,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(path),
        ]
    )


def placeholder_clips(
    terms: list[str],
    dest: Path,
    aspect: str,
    duration: float,
    *,
    width: int = 0,
    height: int = 0,
    fps: int = 30,
    count: int = 4,
) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    w, h = frame_size(aspect, width, height)
    labels = terms or ["城市", "街头", "自然光", "特写"]
    paths: list[Path] = []
    for index in range(max(1, count)):
        path = dest / f"placeholder-{index}.mp4"
        render_placeholder(
            path,
            labels[index % len(labels)],
            w,
            h,
            max(1.0, duration),
            _COLORS[index % len(_COLORS)],
            fps,
        )
        paths.append(path)
    return paths


def _pick_pexels_file(video: dict[str, Any], target_w: int) -> str | None:
    files = video.get("video_files") or []
    mp4s = []
    for item in files:
        link = str(item.get("link") or "")
        kind = str(item.get("file_type") or "")
        if "mp4" in kind or link.lower().endswith(".mp4"):
            mp4s.append(item)
    if not mp4s:
        return None
    mp4s.sort(key=lambda item: abs(int(item.get("width") or 0) - target_w))
    return str(mp4s[0].get("link") or "") or None


def search_pexels(
    api_key: str,
    term: str,
    aspect: str,
    http: httpx.Client,
) -> str | None:
    orientation = "portrait" if aspect == "9:16" else "landscape"
    response = http.get(
        "https://api.pexels.com/videos/search",
        params={"query": term, "orientation": orientation, "per_page": 5, "size": "medium"},
        headers={"Authorization": api_key},
    )
    if response.status_code == 401:
        raise ReelPressError("Pexels API Key 无效。")
    if response.status_code >= 400:
        raise ReelPressError(f"Pexels 搜索失败（{response.status_code}）。")
    videos = response.json().get("videos") or []
    target_w = 1080 if aspect == "9:16" else 1920
    for video in videos:
        link = _pick_pexels_file(video, target_w)
        if link:
            return link
    return None


def search_pixabay(api_key: str, term: str, aspect: str, http: httpx.Client) -> str | None:
    # Pixabay's video endpoint has no portrait/landscape switch. `aspect` stays in the
    # signature so every stock provider is called the same way.
    del aspect
    response = http.get(
        "https://pixabay.com/api/videos/",
        params={"key": api_key, "q": term, "per_page": 5},
    )
    if response.status_code >= 400:
        raise ReelPressError(f"Pixabay 搜索失败（{response.status_code}）。")
    hits = response.json().get("hits") or []
    prefer = ("large", "medium", "small", "tiny")
    for hit in hits:
        videos = hit.get("videos") or {}
        for name in prefer:
            link = str((videos.get(name) or {}).get("url") or "")
            if link:
                return link
    return None


def search_ai_visual(settings: Settings, term: str, aspect: str, duration: float, http: httpx.Client) -> bytes | str:
    """Call a user-supplied image/video API.

    Contract: POST {base_url}/v1/videos
    JSON body: {"prompt", "aspect", "duration", "model"}
    Response JSON: {"url": "https://...mp4"} or {"b64": "<raw mp4 base64>"}
    """
    if not settings.visual_ai_base_url:
        raise ReelPressError("未配置 AI 画面接口。请设置 visual_ai.base_url。")
    headers = {"Content-Type": "application/json"}
    if settings.visual_ai_api_key:
        headers["Authorization"] = f"Bearer {settings.visual_ai_api_key}"
    response = http.post(
        settings.visual_ai_base_url.rstrip("/") + "/v1/videos",
        headers=headers,
        json={
            "prompt": term,
            "aspect": aspect,
            "duration": duration,
            "model": settings.visual_ai_model,
        },
    )
    if response.status_code >= 400:
        raise ReelPressError(f"AI 画面接口返回 {response.status_code}。")
    data = response.json()
    if data.get("b64"):
        return base64.b64decode(data["b64"])
    if data.get("url"):
        return str(data["url"])
    raise ReelPressError("AI 画面接口没有返回 url 或 b64。")


def _download(http: httpx.Client, url: str, path: Path) -> None:
    response = http.get(url)
    if response.status_code >= 400 or not response.content:
        raise ReelPressError(f"素材下载失败（{response.status_code}）。")
    path.write_bytes(response.content)


def collect_clips(
    settings: Settings,
    terms: list[str],
    dest: Path,
    aspect: str,
    *,
    width: int = 0,
    height: int = 0,
    clip_seconds: float = 4,
    provider: str = "",
    http: httpx.Client | None = None,
    warnings: list[str] | None = None,
    count: int | None = None,
) -> list[Path]:
    notes = warnings if warnings is not None else []
    chosen = (provider or settings.stock_provider or "pexels").lower()
    clip_count = count or min(4, max(len(terms), 1))
    dest.mkdir(parents=True, exist_ok=True)
    w, h = frame_size(aspect, width or settings.video_width, height or settings.video_height)
    if chosen in {"placeholder", "none", "offline"}:
        notes.append("使用了本地占位画面，没有请求图库。")
        return placeholder_clips(
            terms, dest, aspect, clip_seconds, width=w, height=h, fps=settings.video_fps, count=clip_count
        )

    client, owns = _client(http)
    paths: list[Path] = []
    try:
        for index, term in enumerate(terms[:5]):
            target = dest / f"clip-{index}.mp4"
            try:
                if chosen == "ai":
                    payload = search_ai_visual(settings, term, aspect, clip_seconds, client)
                    if isinstance(payload, bytes):
                        target.write_bytes(payload)
                    else:
                        _download(client, payload, target)
                elif chosen == "pixabay":
                    if not settings.pixabay_api_key:
                        raise ReelPressError("未配置 Pixabay API Key。")
                    url = search_pixabay(settings.pixabay_api_key, term, aspect, client)
                    if not url:
                        raise ReelPressError(f"Pixabay 没有找到「{term}」的视频。")
                    _download(client, url, target)
                else:
                    if not settings.pexels_api_key:
                        raise ReelPressError("未配置 Pexels API Key。")
                    url = search_pexels(settings.pexels_api_key, term, aspect, client)
                    if not url:
                        raise ReelPressError(f"Pexels 没有找到「{term}」的视频。")
                    _download(client, url, target)
                paths.append(target)
            except ReelPressError as exc:
                notes.append(str(exc))
                message = str(exc)
                if any(token in message for token in ("API Key", "未配置", "无效")):
                    break
                continue
    finally:
        if owns:
            client.close()

    if len(paths) >= 1 and len(paths) < min(len(terms), 3):
        notes.append("部分素材下载失败，已用成功的片段继续合成。")
    if paths:
        return paths
    notes.append("图库不可用，已改用本地占位画面。")
    return placeholder_clips(
        terms,
        dest,
        aspect,
        clip_seconds,
        width=w,
        height=h,
        fps=settings.video_fps,
        count=clip_count,
    )
