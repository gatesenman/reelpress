"""Shared data objects for the generation pipeline and job store."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class Cue:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CopyBundle:
    title: str
    description: str
    hashtags: list[str]
    script: str
    search_terms: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GenerateParams:
    topic: str
    script: str = ""
    aspect: str = "9:16"
    voice: str = ""
    rate: str = ""
    stock_provider: str = ""
    bgm: bool = True
    burn_subtitles: bool = True
    platforms: list[str] = field(default_factory=list)
    account: str = "default"
    publish_at: str | None = None
    publish: bool = False
    native_schedule: bool = False
    mock: bool = False
    stop_at: str = "video"
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerateParams:
        known = {item.name for item in fields(cls)}
        cleaned = {key: value for key, value in data.items() if key in known}
        platforms = cleaned.get("platforms") or []
        cleaned["platforms"] = list(platforms)
        return cls(**cleaned)


@dataclass
class PipelineResult:
    title: str
    description: str
    hashtags: list[str]
    script: str
    search_terms: list[str]
    video_path: str = ""
    audio_path: str = ""
    subtitle_path: str = ""
    duration: float = 0
    warnings: list[str] = field(default_factory=list)
    uploads: list[dict[str, Any]] = field(default_factory=list)
    stopped_at: str = "video"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UploadRequest:
    video_path: str
    title: str
    description: str
    hashtags: list[str]
    account: str = "default"
    schedule_at: str | None = None
    native_schedule: bool = False


@dataclass
class UploadResult:
    platform: str
    success: bool
    url: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
