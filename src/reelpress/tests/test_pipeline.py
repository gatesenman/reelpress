import json
import subprocess

from reelpress.media import ffprobe_bin
from reelpress.models import GenerateParams
from reelpress.pipeline import run_pipeline
from reelpress.tts import EstimatedTTS


def _streams(path) -> set[str]:
    proc = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return {item["codec_type"] for item in data["streams"]}


def test_mock_pipeline_renders_video(settings, tmp_path):
    params = GenerateParams(
        topic="清晨的街道",
        script="清晨的街道还没完全醒来。面包店刚打开灯。",
        aspect="9:16",
        mock=True,
        burn_subtitles=True,
        bgm=False,
    )
    result = run_pipeline(
        params,
        settings,
        tmp_path / "job",
        tts=EstimatedTTS(seconds_per_char=0.18),
    )
    video = tmp_path / "job" / "final.mp4"
    assert result.video_path == str(video)
    assert video.exists()
    assert result.duration > 0.8
    assert {"video", "audio"} <= _streams(video)
    srt = (tmp_path / "job" / "subtitle.srt").read_text(encoding="utf-8")
    assert "清晨" in srt
    script = json.loads((tmp_path / "job" / "script.json").read_text(encoding="utf-8"))
    assert script["script"].startswith("清晨")


def test_stop_at_script_skips_ffmpeg(settings, tmp_path):
    params = GenerateParams(topic="只写文案", script="这是一段口播。", stop_at="script", mock=True)
    result = run_pipeline(params, settings, tmp_path / "job", tts=EstimatedTTS())
    assert result.stopped_at == "script"
    assert result.video_path == ""
    assert not (tmp_path / "job" / "final.mp4").exists()
