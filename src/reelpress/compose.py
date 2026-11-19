"""Assemble clips, voice, burned-in subtitles, and optional music with ffmpeg."""

from __future__ import annotations

from pathlib import Path

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.media import cjk_font, ffmpeg_filter_path, frame_size, probe_duration, run_ffmpeg
from reelpress.models import Cue
from reelpress.subtitles import write_ass, write_srt

_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}


def find_bgm(music_dir: Path, explicit: str = "") -> Path | None:
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
        return None
    if not music_dir.exists():
        return None
    files = [path for path in sorted(music_dir.iterdir()) if path.suffix.lower() in _AUDIO_EXTS and path.is_file()]
    return files[0] if files else None


def _normalize_clip(
    src: Path,
    dst: Path,
    width: int,
    height: int,
    fps: int,
    duration: float,
    preset: str,
    crf: int,
) -> None:
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},format=yuv420p,setsar=1"
    )
    run_ffmpeg(
        [
            "-i",
            str(src),
            "-t",
            f"{max(0.4, duration):.3f}",
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ]
    )


def _concat(clips: list[Path], dst: Path) -> None:
    listing = dst.with_suffix(".txt")
    lines = []
    for clip in clips:
        escaped = clip.resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dst)])


def _encode_args(preset: str, crf: int) -> list[str]:
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]


def compose_video(
    clips: list[Path],
    audio: Path,
    cues: list[Cue],
    output: Path,
    settings: Settings,
    *,
    aspect: str,
    width: int = 0,
    height: int = 0,
    burn_subtitles: bool = True,
    use_bgm: bool = True,
    workdir: Path | None = None,
    warnings: list[str] | None = None,
) -> float:
    if not clips:
        raise ReelPressError("没有可用的画面片段。")
    if not audio.exists():
        raise ReelPressError("没有配音文件，无法合成。")
    work = workdir or output.parent
    work.mkdir(parents=True, exist_ok=True)
    w, h = frame_size(aspect, width or settings.video_width, height or settings.video_height)
    audio_duration = probe_duration(audio)
    if audio_duration <= 0.2:
        raise ReelPressError("配音时长异常，无法合成。")

    segment = min(settings.clip_seconds, max(audio_duration, 1.0))
    normalized: list[Path] = []
    for index, clip in enumerate(clips):
        dst = work / f"norm-{index}.mp4"
        _normalize_clip(clip, dst, w, h, settings.video_fps, segment, settings.video_preset, settings.video_crf)
        normalized.append(dst)

    sequence: list[Path] = []
    covered = 0.0
    guard = 0
    while covered < audio_duration - 0.05 and guard < 80:
        sequence.append(normalized[guard % len(normalized)])
        covered += segment
        guard += 1
    if not sequence:
        sequence = [normalized[0]]

    concat_path = work / "concat.mp4"
    _concat(sequence, concat_path)

    trimmed = work / "trimmed.mp4"
    run_ffmpeg(
        [
            "-i",
            str(concat_path),
            "-t",
            f"{audio_duration:.3f}",
            *_encode_args(settings.video_preset, settings.video_crf),
            "-an",
            str(trimmed),
        ]
    )

    voiced = work / "voiced.mp4"
    bgm = find_bgm(settings.music_dir) if use_bgm else None
    if bgm is not None:
        volume = min(max(settings.bgm_volume, 0.0), 1.0)
        run_ffmpeg(
            [
                "-i",
                str(trimmed),
                "-i",
                str(audio),
                "-stream_loop",
                "-1",
                "-i",
                str(bgm),
                "-filter_complex",
                (
                    "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=1[voice];"
                    f"[2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={volume:.3f}[bed];"
                    "[voice][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
                ),
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
                str(voiced),
            ]
        )
    else:
        run_ffmpeg(
            [
                "-i",
                str(trimmed),
                "-i",
                str(audio),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
                str(voiced),
            ]
        )

    srt_path = work / "subtitle.srt"
    ass_path = work / "subtitle.ass"
    write_srt(cues, srt_path)
    write_ass(cues, ass_path, w, h)

    if burn_subtitles and cues:
        _family, font_dir = cjk_font()
        ass_escaped = ffmpeg_filter_path(ass_path)
        vf = f"ass='{ass_escaped}'"
        if font_dir is not None:
            vf += f":fontsdir='{ffmpeg_filter_path(font_dir)}'"
        try:
            run_ffmpeg(
                [
                    "-i",
                    str(voiced),
                    "-vf",
                    vf,
                    *_encode_args(settings.video_preset, settings.video_crf),
                    "-c:a",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(output),
                ]
            )
        except ReelPressError as exc:
            if warnings is not None:
                warnings.append(f"字幕烧录失败，已输出无字幕成片：{exc}")
            run_ffmpeg(["-i", str(voiced), "-c", "copy", "-movflags", "+faststart", str(output)])
    else:
        run_ffmpeg(["-i", str(voiced), "-c", "copy", "-movflags", "+faststart", str(output)])

    if not output.exists():
        raise ReelPressError("合成结束，但没有找到成片。")
    return probe_duration(output)
