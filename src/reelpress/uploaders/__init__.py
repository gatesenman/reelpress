"""Pluggable publishers. Add a platform by implementing Uploader."""

from reelpress.uploaders.base import Uploader, cookie_path, list_platforms
from reelpress.uploaders.registry import get_uploader, uploader_names

__all__ = ["Uploader", "cookie_path", "get_uploader", "list_platforms", "uploader_names"]
