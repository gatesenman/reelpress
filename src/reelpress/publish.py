"""Publish a finished job now, or leave it scheduled for the local queue."""

from __future__ import annotations

from datetime import datetime, timezone

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.jobs import JobStore, now_iso, parse_user_time
from reelpress.models import UploadRequest, UploadResult
from reelpress.uploaders.registry import default_uploaders


def publish_job(job_id: str, store: JobStore, settings: Settings, uploaders: dict | None = None) -> dict:
    job = store.get(job_id)
    if job is None:
        raise ReelPressError("任务不存在。")
    video = str(job.result.get("video_path") or "")
    if not video:
        raise ReelPressError("这个任务还没有成片，不能发布。")
    platforms = list(job.params.get("platforms") or [])
    if not platforms:
        raise ReelPressError("没有选择发布平台。")
    registry = uploaders or default_uploaders()
    unknown = [name for name in platforms if name not in registry]
    if unknown:
        raise ReelPressError(f"未知平台：{', '.join(unknown)}。")

    if not store.claim_publish(job_id):
        current = store.get(job_id)
        if current and current.status in {"publishing", "published"}:
            return current.to_dict()
        raise ReelPressError("任务当前不能发布。")
    store.update(job_id, error="")
    account = str(job.params.get("account") or "default")
    request = UploadRequest(
        video_path=video,
        title=str(job.result.get("title") or job.topic),
        description=str(job.result.get("description") or ""),
        hashtags=list(job.result.get("hashtags") or []),
        account=account,
        schedule_at=job.publish_at if job.params.get("native_schedule") else None,
        native_schedule=bool(job.params.get("native_schedule")),
    )
    existing = [item for item in (job.result.get("uploads") or []) if item.get("success")]
    done = {item.get("platform") for item in existing}
    results = list(existing)
    errors: list[str] = []
    for name in platforms:
        if name in done:
            continue
        try:
            outcome = registry[name].upload(settings, request)
        except ReelPressError as exc:
            outcome = UploadResult(platform=name, success=False, message=str(exc))
        except Exception as exc:
            outcome = UploadResult(platform=name, success=False, message=f"发布失败：{exc}")
        results.append(outcome.to_dict())
        if not outcome.success:
            errors.append(f"{name}：{outcome.message}")

    payload = dict(job.result)
    payload["uploads"] = results
    if errors:
        updated = store.update(
            job_id,
            status="publish_failed",
            stage="publish",
            progress=100,
            error="；".join(errors),
            result=payload,
        )
    else:
        updated = store.update(
            job_id,
            status="published",
            stage="done",
            progress=100,
            error="",
            result=payload,
        )
    return updated.to_dict()


def schedule_or_publish(
    job_id: str,
    store: JobStore,
    settings: Settings,
    *,
    platforms: list[str],
    account: str,
    publish_at: str | None,
    native_schedule: bool = False,
    uploaders: dict | None = None,
) -> dict:
    job = store.get(job_id)
    if job is None:
        raise ReelPressError("任务不存在。")
    if not job.result.get("video_path"):
        raise ReelPressError("成片还没准备好。")
    if not platforms:
        raise ReelPressError("请至少选择一个平台。")
    params = dict(job.params)
    params["platforms"] = platforms
    params["account"] = account or "default"
    params["publish"] = True
    params["native_schedule"] = native_schedule
    when = parse_user_time(publish_at) if publish_at else None
    params["publish_at"] = when
    future = bool(when and when > datetime.now(timezone.utc).isoformat() and not native_schedule)
    if future:
        updated = store.update(
            job_id,
            params=params,
            status="scheduled",
            stage="publish",
            progress=100,
            publish_at=when,
            error="",
        )
        return updated.to_dict()
    store.update(job_id, params=params, publish_at=when, error="")
    # Refresh so publish_job sees the new platforms.
    return publish_job(job_id, store, settings, uploaders=uploaders)


def iso_now() -> str:
    return now_iso()
