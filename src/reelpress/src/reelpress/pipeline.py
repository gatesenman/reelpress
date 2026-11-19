"""Stage runner: copy -> voice -> captions -> footage -> ffmpeg.

Intermediate files are written under the job directory, the same checkpoint
idea as MoneyPrinterTurbo, so a failed stage can be inspected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.llm import generate_copy
from reelpress.materials import collect_clips
from reelpress.media import frame_size
from reelpress.models import GenerateParams, PipelineResult
from reelpress.subtitles import build_cues, write_ass, write_srt
from reelpress.tts import EdgeTTS, EstimatedTTS, TTSProvider

ProgressFn = Callable[[str, int, str], None]

_STOPS = {"script", "audio", "subtitle", "materials", "video"}


def run_pipeline(
    params: GenerateParams,
    settings: Settings,
    workdir: Path,
    *,
    tts: TTSProvider | None = None,
    http: httpx.Client | None = None,
    on_progress: ProgressFn | None = None,
) -> PipelineResult:
    if params.stop_at not in _STOPS:
        raise ReelPressError("stop_at 只能是 script、audio、subtitle、materials 或 video。")
    if params.aspect not in {"9:16", "16:9"}:
        raise ReelPressError("画幅只支持 9:16 或 16:9。")
    topic = params.topic.strip()
    if not topic and not params.script.strip() and not params.mock:
        raise ReelPressError("请填写主题，或直接粘贴口播文案。")

    workdir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    def progress(stage: str, value: int, message: str) -> None:
        if on_progress:
            on_progress(stage, value, message)

    progress("script", 8, "正在写文案")
    bundle = generate_copy(
        settings,
        topic or "未命名",
        params.script,
        params.aspect,
        mock=params.mock,
    )
    warnings.extend(bundle.warnings)
    script_path = workdir / "script.json"
    script_path.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    result = PipelineResult(
        title=bundle.title,
        description=bundle.description,
        hashtags=bundle.hashtags,
        script=bundle.script,
        search_terms=bundle.search_terms,
        warnings=warnings,
        stopped_at="script",
    )
    if params.stop_at == "script":
        progress("script", 100, "文案已完成")
        return result

    progress("audio", 28, "正在合成配音")
    voice = tts
    if voice is None:
        voice = EstimatedTTS() if params.mock or settings.tts_provider == "estimated" else EdgeTTS()
    audio_path = workdir / ("audio.m4a" if isinstance(voice, EstimatedTTS) else "audio.mp3")
    cues = voice.synthesize(
        bundle.script,
        audio_path,
        params.voice or settings.tts_voice,
        params.rate or settings.tts_rate,
    )
    result.audio_path = str(audio_path)
    result.stopped_at = "audio"
    if params.stop_at == "audio":
        progress("audio", 100, "配音已完成")
        result.warnings = warnings
        return result

    progress("subtitle", 46, "正在对齐字幕")
    width, height = frame_size(params.aspect, params.width or settings.video_width, params.height or settings.video_height)
    if not cues:
        from reelpress.media import probe_duration

        cues = build_cues(bundle.script, probe_duration(audio_path))
    srt_path = workdir / "subtitle.srt"
    ass_path = workdir / "subtitle.ass"
    write_srt(cues, srt_path)
    write_ass(cues, ass_path, width, height)
    result.subtitle_path = str(srt_path)
    result.stopped_at = "subtitle"
    if params.stop_at == "subtitle":
        progress("subtitle", 100, "字幕已完成")
        result.warnings = warnings
        return result

    progress("materials", 62, "正在准备画面")
    provider = params.stock_provider or ("placeholder" if params.mock else settings.stock_provider)
    clips = collect_clips(
        settings,
        bundle.search_terms,
        workdir / "clips",
        params.aspect,
        width=width,
        height=height,
        clip_seconds=min(settings.clip_seconds, 3.0 if params.mock else settings.clip_seconds),
        provider=provider,
        http=http,
        warnings=warnings,
        count=2 if params.mock else None,
    )
    result.stopped_at = "materials"
    if params.stop_at == "materials":
        progress("materials", 100, "素材已准备")
        result.warnings = warnings
        return result

    progress("compose", 82, "正在合成成片")
    from reelpress.compose import compose_video

    final_path = workdir / "final.mp4"
    duration = compose_video(
        clips,
        audio_path,
        cues,
        final_path,
        settings,
        aspect=params.aspect,
        width=width,
        height=height,
        burn_subtitles=params.burn_subtitles,
        use_bgm=params.bgm and not params.mock,
        workdir=workdir,
        warnings=warnings,
    )
    result.video_path = str(final_path)
    result.duration = duration
    result.subtitle_path = str(srt_path)
    result.stopped_at = "video"
    result.warnings = warnings
    progress("done", 100, "成片已就绪")
    (workdir / "result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
