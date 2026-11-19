"""Caption splitting plus SRT and ASS writers.

Chinese lines stay short so they remain readable on a vertical phone frame.
"""

from __future__ import annotations

import re
from pathlib import Path

from reelpress.media import cjk_font
from reelpress.models import Cue

_PUNCT = "。！？!?；;"


def split_caption_lines(text: str, max_chars: int = 16) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    parts = re.split(rf"[{re.escape(_PUNCT)}\n]+", cleaned)
    lines: list[str] = []
    for part in parts:
        chunk = part.strip(" ，,、 ")
        if not chunk:
            continue
        while len(chunk) > max_chars:
            window = chunk[: max_chars + 1]
            cut = max(window.rfind("，"), window.rfind(","), window.rfind("、"), window.rfind(" "))
            if cut < 4:
                cut = max_chars
            piece = chunk[:cut].strip(" ，,、")
            if piece:
                lines.append(piece)
            chunk = chunk[cut:].strip(" ，,、")
        if chunk:
            lines.append(chunk)
    return lines


def cues_from_lines(lines: list[str], duration: float) -> list[Cue]:
    if not lines:
        return []
    duration = max(duration, 0.6)
    weights = [max(len(line), 1) for line in lines]
    total = sum(weights)
    cues: list[Cue] = []
    cursor = 0.0
    for line, weight in zip(lines, weights, strict=True):
        span = duration * weight / total
        end = min(duration, cursor + span)
        if end <= cursor:
            end = min(duration, cursor + 0.2)
        cues.append(Cue(start=cursor, end=end, text=line))
        cursor = end
    if cues:
        cues[-1].end = duration
    return cues


def to_seconds(value: float | int) -> float:
    number = float(value)
    # edge-tts WordBoundary offsets are 100-nanosecond ticks.
    if number > 10000:
        return number / 10_000_000
    return number


def cues_from_boundaries(boundaries: list[dict], max_chars: int = 16) -> list[Cue]:
    words: list[tuple[float, float, str]] = []
    for item in boundaries:
        text = str(item.get("text") or "")
        if not text:
            continue
        start = to_seconds(item.get("offset") or 0)
        duration = to_seconds(item.get("duration") or 0)
        words.append((start, start + max(duration, 0.05), text))
    if not words:
        return []
    cues: list[Cue] = []
    buf = ""
    start = 0.0
    end = 0.0
    begun = False
    for word_start, word_end, text in words:
        if not begun:
            start = word_start
            begun = True
        if buf and len(buf) + len(text) > max_chars:
            cues.append(Cue(start=start, end=max(end, start + 0.2), text=buf.strip()))
            buf = text
            start = word_start
            end = word_end
        else:
            buf += text
            end = word_end
        if text.endswith(tuple(_PUNCT)):
            cues.append(Cue(start=start, end=max(end, start + 0.2), text=buf.strip(" ，,、")))
            buf = ""
            begun = False
    if buf.strip():
        cues.append(Cue(start=start, end=max(end, start + 0.2), text=buf.strip(" ，,、")))
    return [cue for cue in cues if cue.text]


def _srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _ass_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    centi = int(round(seconds * 100))
    hours, centi = divmod(centi, 360000)
    minutes, centi = divmod(centi, 6000)
    secs, centi = divmod(centi, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centi:02d}"


def escape_ass(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def write_srt(cues: list[Cue], path: Path) -> None:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{cue.text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def write_ass(cues: list[Cue], path: Path, width: int, height: int) -> None:
    family, _directory = cjk_font()
    font_size = 64 if height > width else 48
    margin_v = 180 if height > width else 72
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{family},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,2,64,64,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        lines.append(
            f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},Default,,0,0,0,,{escape_ass(cue.text)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_cues(script: str, duration: float, boundaries: list[dict] | None = None) -> list[Cue]:
    if boundaries:
        cues = cues_from_boundaries(boundaries)
        if cues:
            return cues
    lines = split_caption_lines(script)
    return cues_from_lines(lines, duration)
