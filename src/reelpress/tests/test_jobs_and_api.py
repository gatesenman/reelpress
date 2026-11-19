import time
from datetime import datetime, timedelta, timezone

import pytest

from reelpress.errors import ReelPressError
from reelpress.jobs import JobStore, parse_user_time
from reelpress.models import GenerateParams, UploadResult
from reelpress.publish import publish_job, schedule_or_publish


class FakeUploader:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def upload(self, settings, request):
        del settings
        self.calls += 1
        if self.fail:
            raise ReelPressError("平台拒绝了这次发布。")
        return UploadResult(platform="douyin", success=True, message="已点击发布", url="")


def test_parse_user_time():
    assert parse_user_time("") is None
    parsed = parse_user_time("2026-10-10T20:00:00+08:00")
    assert parsed.endswith("+00:00")
    assert "12:00:00" in parsed
    with pytest.raises(ReelPressError):
        parse_user_time("明天晚上")


def test_schedule_waits_and_publish_uses_uploader(settings, tmp_path):
    store = JobStore(settings.db_path)
    params = GenerateParams(topic="夜路", script="夜路很短。", mock=True)
    job = store.create(params)
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    store.update(
        job.id,
        status="succeeded",
        result={"video_path": str(video), "title": "夜路", "description": "短", "hashtags": ["#夜"]},
    )
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    uploader = FakeUploader()
    scheduled = schedule_or_publish(
        job.id,
        store,
        settings,
        platforms=["douyin"],
        account="shop",
        publish_at=future,
        uploaders={"douyin": uploader},
    )
    assert scheduled["status"] == "scheduled"
    assert uploader.calls == 0
    assert store.due_for_publish() == []

    store.update(job.id, publish_at="2020-01-01T00:00:00+00:00", status="scheduled")
    due = store.due_for_publish()
    assert [item.id for item in due] == [job.id]
    published = publish_job(job.id, store, settings, uploaders={"douyin": uploader})
    assert published["status"] == "published"
    assert uploader.calls == 1

    again = FakeUploader()
    second = publish_job(job.id, store, settings, uploaders={"douyin": again})
    assert second["status"] == "published"
    assert again.calls == 0
    store.close()


def test_publish_failure_is_recorded(settings, tmp_path):
    store = JobStore(settings.db_path)
    job = store.create(GenerateParams(topic="失败", platforms=["douyin"], publish=True))
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video")
    store.update(job.id, result={"video_path": str(video), "title": "失败", "description": "", "hashtags": []})
    result = publish_job(job.id, store, settings, uploaders={"douyin": FakeUploader(fail=True)})
    assert result["status"] == "publish_failed"
    assert "拒绝" in result["error"]
    retry = FakeUploader()
    recovered = publish_job(job.id, store, settings, uploaders={"douyin": retry})
    assert recovered["status"] == "published"
    assert retry.calls == 1
    store.close()


def test_api_health_settings_and_mock_job(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ffmpeg"] is True
    page = client.get("/")
    assert page.status_code == 200
    assert "映流" in page.text
    assert "工作台" in page.text
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert settings.json()["llm_api_key"]["configured"] is False
    names = [item["name"] for item in client.get("/api/platforms").json()["platforms"]]
    assert {"youtube", "douyin", "bilibili", "kuaishou", "xiaohongshu"} <= set(names)
    youtube = client.get("/api/oauth/youtube/start", follow_redirects=False)
    assert youtube.status_code == 400

    created = client.post(
        "/api/jobs",
        json={
            "topic": "清晨的街道",
            "script": "清晨的街道还没完全醒来。面包店刚打开灯。",
            "mock": True,
            "aspect": "9:16",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["id"]
    job = {}
    for _ in range(80):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.25)
    assert job["status"] == "succeeded", job
    video = client.get(f"/api/jobs/{job_id}/video")
    assert video.status_code == 200
    assert video.headers["content-type"].startswith("video/mp4")
    assert len(video.content) > 500
    removed = client.delete(f"/api/jobs/{job_id}")
    assert removed.status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_api_rejects_empty_topic(client):
    response = client.post("/api/jobs", json={"topic": "", "script": ""})
    assert response.status_code == 400
    assert "主题" in response.json()["detail"]
