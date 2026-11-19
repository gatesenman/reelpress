"""Load settings from defaults, config.toml, data/settings.json, then env.

Environment variables always win so secrets injected by the host are not
overwritten by the web UI.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reelpress.errors import ReelPressError

DEFAULT_LLM_BASE = "https://api.openai.com/v1"

ENV_MAP: dict[str, tuple[str, str]] = {
    "REELPRESS_DATA_DIR": ("app", "data_dir"),
    "REELPRESS_LLM_API_KEY": ("llm", "api_key"),
    "REELPRESS_LLM_BASE_URL": ("llm", "base_url"),
    "REELPRESS_LLM_MODEL": ("llm", "model"),
    "REELPRESS_PEXELS_API_KEY": ("stock", "pexels_api_key"),
    "REELPRESS_PIXABAY_API_KEY": ("stock", "pixabay_api_key"),
    "REELPRESS_VISUAL_AI_BASE_URL": ("visual_ai", "base_url"),
    "REELPRESS_VISUAL_AI_API_KEY": ("visual_ai", "api_key"),
    "REELPRESS_VISUAL_AI_MODEL": ("visual_ai", "model"),
    "REELPRESS_YOUTUBE_CLIENT_ID": ("youtube", "client_id"),
    "REELPRESS_YOUTUBE_CLIENT_SECRET": ("youtube", "client_secret"),
    "REELPRESS_TTS_VOICE": ("tts", "voice"),
    "REELPRESS_UPLOAD_CDP_URL": ("upload", "cdp_url"),
}

SECRET_FIELDS = {
    ("llm", "api_key"),
    ("stock", "pexels_api_key"),
    ("stock", "pixabay_api_key"),
    ("visual_ai", "api_key"),
    ("youtube", "client_secret"),
}


def _defaults() -> dict[str, Any]:
    return {
        "app": {
            "data_dir": "data",
            "host": "127.0.0.1",
            "port": 8765,
        },
        "llm": {
            "base_url": DEFAULT_LLM_BASE,
            "api_key": "",
            "model": "gpt-4o-mini",
            "temperature": 0.7,
        },
        "tts": {
            "provider": "edge",
            "voice": "zh-CN-XiaoxiaoNeural",
            "rate": "+0%",
        },
        "stock": {
            "provider": "pexels",
            "pexels_api_key": "",
            "pixabay_api_key": "",
        },
        "visual_ai": {
            "base_url": "",
            "api_key": "",
            "model": "",
        },
        "video": {
            "aspect": "9:16",
            "fps": 30,
            "clip_seconds": 4,
            "bgm_volume": 0.14,
            "preset": "veryfast",
            "crf": 23,
            "width": 0,
            "height": 0,
        },
        "youtube": {
            "client_id": "",
            "client_secret": "",
            "redirect_uri": "http://127.0.0.1:8765/api/oauth/youtube/callback",
        },
        "upload": {
            "headless": False,
            "cdp_url": "",
            "login_timeout": 180,
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def config_path() -> Path | None:
    explicit = os.environ.get("REELPRESS_CONFIG", "").strip()
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    local = Path("config.toml")
    return local if local.exists() else None


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ReelPressError(f"配置文件格式不正确：{path}")
    return data


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReelPressError(f"设置文件损坏：{path}") from exc
    if not isinstance(data, dict):
        raise ReelPressError(f"设置文件格式不正确：{path}")
    return data


def _apply_env(raw: dict[str, Any]) -> dict[str, set[tuple[str, str]]]:
    """Apply env overrides. Returns which secret fields came from the environment."""
    from_env: set[tuple[str, str]] = set()
    for env_name, (section, key) in ENV_MAP.items():
        if env_name not in os.environ or os.environ[env_name] == "":
            continue
        raw.setdefault(section, {})
        raw[section][key] = os.environ[env_name]
        from_env.add((section, key))
    return from_env


@dataclass
class Settings:
    data_dir: Path
    host: str
    port: int
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_temperature: float
    tts_provider: str
    tts_voice: str
    tts_rate: str
    stock_provider: str
    pexels_api_key: str
    pixabay_api_key: str
    visual_ai_base_url: str
    visual_ai_api_key: str
    visual_ai_model: str
    video_aspect: str
    video_fps: int
    clip_seconds: float
    bgm_volume: float
    video_preset: str
    video_crf: int
    video_width: int
    video_height: int
    youtube_client_id: str
    youtube_client_secret: str
    youtube_redirect_uri: str
    upload_headless: bool
    upload_cdp_url: str
    login_timeout: int
    env_locked: set[tuple[str, str]] = field(default_factory=set)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "reelpress.db"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def cookie_dir(self) -> Path:
        return self.data_dir / "cookies"

    @property
    def token_dir(self) -> Path:
        return self.data_dir / "tokens"

    @property
    def music_dir(self) -> Path:
        return self.data_dir / "music"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    def llm_configured(self) -> bool:
        if self.llm_api_key.strip():
            return True
        return self.llm_base_url.rstrip("/") != DEFAULT_LLM_BASE

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.cookie_dir,
            self.token_dir,
            self.music_dir,
            self.jobs_dir,
            self.data_dir / "login",
        ):
            path.mkdir(parents=True, exist_ok=True)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def settings_from_raw(raw: dict[str, Any], env_locked: set[tuple[str, str]] | None = None) -> Settings:
    app = raw["app"]
    llm = raw["llm"]
    tts = raw["tts"]
    stock = raw["stock"]
    visual = raw["visual_ai"]
    video = raw["video"]
    youtube = raw["youtube"]
    upload = raw["upload"]
    return Settings(
        data_dir=Path(str(app["data_dir"])).expanduser(),
        host=str(app.get("host") or "127.0.0.1"),
        port=int(app.get("port") or 8765),
        llm_base_url=str(llm.get("base_url") or DEFAULT_LLM_BASE).rstrip("/"),
        llm_api_key=str(llm.get("api_key") or ""),
        llm_model=str(llm.get("model") or "gpt-4o-mini"),
        llm_temperature=float(llm.get("temperature") or 0.7),
        tts_provider=str(tts.get("provider") or "edge"),
        tts_voice=str(tts.get("voice") or "zh-CN-XiaoxiaoNeural"),
        tts_rate=str(tts.get("rate") or "+0%"),
        stock_provider=str(stock.get("provider") or "pexels"),
        pexels_api_key=str(stock.get("pexels_api_key") or ""),
        pixabay_api_key=str(stock.get("pixabay_api_key") or ""),
        visual_ai_base_url=str(visual.get("base_url") or "").rstrip("/"),
        visual_ai_api_key=str(visual.get("api_key") or ""),
        visual_ai_model=str(visual.get("model") or ""),
        video_aspect=str(video.get("aspect") or "9:16"),
        video_fps=int(video.get("fps") or 30),
        clip_seconds=float(video.get("clip_seconds") or 4),
        bgm_volume=float(video.get("bgm_volume") if video.get("bgm_volume") is not None else 0.14),
        video_preset=str(video.get("preset") or "veryfast"),
        video_crf=int(video.get("crf") or 23),
        video_width=int(video.get("width") or 0),
        video_height=int(video.get("height") or 0),
        youtube_client_id=str(youtube.get("client_id") or ""),
        youtube_client_secret=str(youtube.get("client_secret") or ""),
        youtube_redirect_uri=str(
            youtube.get("redirect_uri") or "http://127.0.0.1:8765/api/oauth/youtube/callback"
        ),
        upload_headless=_as_bool(upload.get("headless", False)),
        upload_cdp_url=str(upload.get("cdp_url") or ""),
        login_timeout=int(upload.get("login_timeout") or 180),
        env_locked=set(env_locked or ()),
    )


def load_raw() -> tuple[dict[str, Any], set[tuple[str, str]]]:
    raw = _defaults()
    path = config_path()
    if path is not None:
        raw = _deep_merge(raw, _read_toml(path))
    # data_dir may already be overridden by the toml; settings.json lives inside it
    # unless REELPRESS_DATA_DIR points elsewhere. Apply the env data dir first.
    if "REELPRESS_DATA_DIR" in os.environ:
        raw.setdefault("app", {})
        raw["app"]["data_dir"] = os.environ["REELPRESS_DATA_DIR"]
    data_dir = Path(str(raw["app"]["data_dir"])).expanduser()
    settings_file = data_dir / "settings.json"
    if settings_file.exists():
        raw = _deep_merge(raw, _read_json(settings_file))
    env_locked = _apply_env(raw)
    return raw, env_locked


def load_settings() -> Settings:
    raw, env_locked = load_raw()
    settings = settings_from_raw(raw, env_locked)
    settings.ensure_dirs()
    return settings


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"


def public_settings(settings: Settings) -> dict[str, Any]:
    def secret(section: str, key: str, value: str) -> dict[str, Any]:
        return {
            "configured": bool(value),
            "hint": mask_secret(value),
            "from_env": (section, key) in settings.env_locked,
        }

    return {
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_temperature": settings.llm_temperature,
        "llm_api_key": secret("llm", "api_key", settings.llm_api_key),
        "llm_configured": settings.llm_configured(),
        "tts_provider": settings.tts_provider,
        "tts_voice": settings.tts_voice,
        "tts_rate": settings.tts_rate,
        "stock_provider": settings.stock_provider,
        "pexels_api_key": secret("stock", "pexels_api_key", settings.pexels_api_key),
        "pixabay_api_key": secret("stock", "pixabay_api_key", settings.pixabay_api_key),
        "visual_ai_base_url": settings.visual_ai_base_url,
        "visual_ai_model": settings.visual_ai_model,
        "visual_ai_api_key": secret("visual_ai", "api_key", settings.visual_ai_api_key),
        "video_aspect": settings.video_aspect,
        "video_fps": settings.video_fps,
        "clip_seconds": settings.clip_seconds,
        "bgm_volume": settings.bgm_volume,
        "youtube_client_id": settings.youtube_client_id,
        "youtube_client_secret": secret("youtube", "client_secret", settings.youtube_client_secret),
        "youtube_redirect_uri": settings.youtube_redirect_uri,
        "upload_headless": settings.upload_headless,
        "upload_cdp_url": settings.upload_cdp_url,
        "data_dir": str(settings.data_dir),
    }


_UI_TO_RAW = {
    "llm_base_url": ("llm", "base_url"),
    "llm_model": ("llm", "model"),
    "llm_temperature": ("llm", "temperature"),
    "llm_api_key": ("llm", "api_key"),
    "tts_provider": ("tts", "provider"),
    "tts_voice": ("tts", "voice"),
    "tts_rate": ("tts", "rate"),
    "stock_provider": ("stock", "provider"),
    "pexels_api_key": ("stock", "pexels_api_key"),
    "pixabay_api_key": ("stock", "pixabay_api_key"),
    "visual_ai_base_url": ("visual_ai", "base_url"),
    "visual_ai_model": ("visual_ai", "model"),
    "visual_ai_api_key": ("visual_ai", "api_key"),
    "video_aspect": ("video", "aspect"),
    "bgm_volume": ("video", "bgm_volume"),
    "youtube_client_id": ("youtube", "client_id"),
    "youtube_client_secret": ("youtube", "client_secret"),
    "youtube_redirect_uri": ("youtube", "redirect_uri"),
    "upload_headless": ("upload", "headless"),
    "upload_cdp_url": ("upload", "cdp_url"),
}


def _keep_previous(incoming: Any, previous: str) -> bool:
    if incoming is None:
        return True
    text = str(incoming)
    if text == "":
        return False
    if "****" in text:
        return True
    if previous and text == mask_secret(previous):
        return True
    return False


def save_user_settings(updates: dict[str, Any], settings: Settings | None = None) -> Settings:
    """Persist UI edits to data/settings.json. Env-locked keys are ignored."""
    current = settings or load_settings()
    raw, _env = load_raw()
    # Start from the on-disk user file so we don't copy env-only secrets into it.
    user_path = current.settings_path
    user_raw: dict[str, Any] = _read_json(user_path) if user_path.exists() else {}
    for ui_key, (section, key) in _UI_TO_RAW.items():
        if ui_key not in updates:
            continue
        if (section, key) in current.env_locked:
            continue
        value = updates[ui_key]
        if (section, key) in SECRET_FIELDS:
            prev_value = str(raw.get(section, {}).get(key) or "")
            if _keep_previous(value, prev_value):
                continue
            value = "" if value is None else str(value)
        user_raw.setdefault(section, {})
        user_raw[section][key] = value

    current.ensure_dirs()
    payload = json.dumps(user_raw, ensure_ascii=False, indent=2)
    user_path.write_text(payload, encoding="utf-8")
    try:
        user_path.chmod(0o600)
    except OSError:
        pass
    return load_settings()
