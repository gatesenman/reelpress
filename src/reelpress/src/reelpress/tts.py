"""Text-to-speech providers.

edge-tts is the free default. Tests and the offline demo use EstimatedTTS,
which writes silent audio and even caption timings so the rest of the
pipeline can still run.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from reelpress.errors import ReelPressError
from reelpress.media import probe_duration, write_silence
from reelpress.models import Cue
from reelpress.subtitles import build_cues, cues_from_boundaries


class TTSProvider(Protocol):
    def synthesize(self, text: str, output: Path, voice: str, rate: str) -> list[Cue]:
        """Write narration audio and return caption cues aligned to it."""


class EstimatedTTS:
    """Silent stand-in used by tests, offline demo, and explicit fallback."""

    def __init__(self, seconds_per_char: float = 0.22) -> None:
        self.seconds_per_char = seconds_per_char

    def synthesize(self, text: str, output: Path, voice: str, rate: str) -> list[Cue]:
        del voice, rate
        duration = _estimate_duration(text, self.seconds_per_char)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_silence(output, duration)
        actual = probe_duration(output)
        return build_cues(text, actual or duration)


class EdgeTTS:
    def synthesize(self, text: str, output: Path, voice: str, rate: str) -> list[Cue]:
        try:
            import edge_tts
        except ImportError as exc:
            raise ReelPressError("未安装 edge-tts。请执行 pip install edge-tts。") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        boundaries = asyncio.run(_stream_edge(edge_tts, text, voice or "zh-CN-XiaoxiaoNeural", rate or "+0%", output))
        if not output.exists() or output.stat().st_size < 64:
            raise ReelPressError("语音合成没有写出音频。请检查网络是否能访问微软语音服务。")
        duration = probe_duration(output)
        cues = cues_from_boundaries(boundaries) if boundaries else []
        if not cues:
            cues = build_cues(text, duration)
        return cues


async def _stream_edge(edge_tts, text: str, voice: str, rate: str, output: Path) -> list[dict]:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    boundaries: list[dict] = []
    with output.open("wb") as handle:
        async for chunk in communicate.stream():
            kind = chunk.get("type")
            if kind == "audio":
                handle.write(chunk.get("data") or b"")
            elif kind in {"WordBoundary", "SentenceBoundary"}:
                boundaries.append(chunk)
    # Prefer word timings when both were emitted.
    words = [item for item in boundaries if item.get("type") == "WordBoundary"]
    return words or boundaries


def build_tts(provider: str, *, mock: bool = False) -> TTSProvider:
    if mock or provider == "estimated":
        return EstimatedTTS()
    if provider in {"edge", "edge-tts", ""}:
        return EdgeTTS()
    raise ReelPressError(f"不支持的语音引擎：{provider}。当前可选 edge 或 estimated。")


def _estimate_duration(text: str, seconds_per_char: float) -> float:
    import re

    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(re.sub(r"[\u4e00-\u9fff\s]", "", text))
    return max(1.6, zh * seconds_per_char + other * 0.06 + 0.35)
