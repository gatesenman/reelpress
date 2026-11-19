"""Uploader interface shared by the official API and browser publishers."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Protocol

from reelpress.config import Settings
from reelpress.models import UploadRequest, UploadResult


class Uploader(Protocol):
    name: str
    label: str
    method: str

    def cookie_file(self, settings: Settings, account: str) -> Path:
        ...

    def check(self, settings: Settings, account: str, *, live: bool = False) -> bool:
        ...

    def login(
        self,
        settings: Settings,
        account: str,
        *,
        on_qr=None,
        headed: bool | None = None,
        cdp_url: str = "",
        timeout: int | None = None,
    ) -> Path:
        ...

    def upload(self, settings: Settings, request: UploadRequest) -> UploadResult:
        ...


def safe_account(account: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", (account or "default").strip()) or "default"
    return cleaned[:40]


def cookie_path(settings: Settings, platform: str, account: str) -> Path:
    return settings.cookie_dir / f"{platform}_{safe_account(account)}.json"


def cookie_file_valid(path: Path, names: tuple[str, ...]) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    now = time.time()
    for cookie in data.get("cookies") or []:
        if cookie.get("name") not in names or not cookie.get("value"):
            continue
        expires = cookie.get("expires", -1)
        try:
            exp = float(expires)
        except (TypeError, ValueError):
            exp = -1
        if exp < 0 or exp > now:
            return True
    return False


def list_platforms() -> list[dict[str, str]]:
    from reelpress.uploaders.platforms import PLATFORM_SPECS
    from reelpress.uploaders.youtube import YOUTUBE_LABEL

    rows = [
        {"name": "youtube", "label": YOUTUBE_LABEL, "method": "youtube-data-api"},
    ]
    for spec in PLATFORM_SPECS:
        rows.append({"name": spec.name, "label": spec.label, "method": "playwright"})
    return rows
