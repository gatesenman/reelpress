"""Build the default uploader set. Tests can pass their own mapping."""

from __future__ import annotations

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.uploaders.platforms import PLATFORM_SPECS, BrowserUploader
from reelpress.uploaders.youtube import YouTubeUploader


def uploader_names() -> list[str]:
    return ["youtube", *[spec.name for spec in PLATFORM_SPECS]]


def get_uploader(name: str, settings: Settings | None = None, *, session_factory=None, http=None):
    del settings
    if name == "youtube":
        return YouTubeUploader(client=http)
    for spec in PLATFORM_SPECS:
        if spec.name == name:
            return BrowserUploader(spec, session_factory=session_factory)
    raise ReelPressError(f"未知平台：{name}。可选：{', '.join(uploader_names())}。")


def default_uploaders(http=None, session_factory=None) -> dict:
    uploaders = {"youtube": YouTubeUploader(client=http)}
    for spec in PLATFORM_SPECS:
        uploaders[spec.name] = BrowserUploader(spec, session_factory=session_factory)
    return uploaders
