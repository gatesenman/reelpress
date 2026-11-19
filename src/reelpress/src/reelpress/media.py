"""Small ffmpeg helpers shared by TTS, stock placeholders, and the composer."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from reelpress.errors import ReelPressError

ASPECT_SIZES = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise ReelPressError("未找到 ffmpeg。请先安装 ffmpeg，再生成视频。")
    return path


def ffprobe_bin() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise ReelPressError("未找到 ffprobe。它通常和 ffmpeg 一起安装。")
    return path


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run_ffmpeg(args: list[str]) -> None:
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "未知错误").strip()
        raise ReelPressError(f"ffmpeg 失败：{detail[-800:]}")


def probe_duration(path: Path) -> float:
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ReelPressError(f"无法读取媒体时长：{path.name}")
    try:
        return max(0.0, float(proc.stdout.strip()))
    except ValueError as exc:
        raise ReelPressError(f"无法读取媒体时长：{path.name}") from exc


def cjk_font() -> tuple[str, Path | None]:
    """Return a font family name and the directory that contains it."""
    candidates = [
        ("WenQuanYi Micro Hei", Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")),
        ("Droid Sans Fallback", Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")),
        ("Noto Sans CJK SC", Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")),
        ("Noto Sans CJK SC", Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc")),
    ]
    for family, file_path in candidates:
        if file_path.exists():
            return family, file_path.parent
    return "Sans", None


def cjk_font_file() -> Path | None:
    named = [
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for path in named:
        if path.exists():
            return path
    return None


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", "")
        .replace("%", r"\%")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def ffmpeg_filter_path(path: Path) -> str:
    text = path.resolve().as_posix().replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
    return text


def frame_size(aspect: str, width: int = 0, height: int = 0) -> tuple[int, int]:
    if width > 0 and height > 0:
        return width - width % 2, height - height % 2
    if aspect not in ASPECT_SIZES:
        raise ReelPressError("画幅只支持 9:16 或 16:9。")
    return ASPECT_SIZES[aspect]


def write_silence(path: Path, duration: float) -> None:
    duration = max(0.4, duration)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
        ]
    )
