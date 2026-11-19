"""HTTP API and the Chinese web UI."""

from __future__ import annotations

import json
import secrets
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from reelpress import __version__
from reelpress.config import Settings, load_settings, public_settings, save_user_settings
from reelpress.errors import ReelPressError
from reelpress.jobs import ACTIVE, JobRunner, JobStore
from reelpress.media import has_ffmpeg
from reelpress.models import GenerateParams
from reelpress.publish import schedule_or_publish
from reelpress.uploaders.base import list_platforms
from reelpress.uploaders.registry import get_uploader
from reelpress.uploaders.youtube import build_auth_url, exchange_code

STATIC_DIR = Path(__file__).resolve().parent / "static"


class JobIn(BaseModel):
    topic: str = ""
    script: str = ""
    aspect: str = "9:16"
    voice: str = ""
    rate: str = ""
    stock_provider: str = ""
    bgm: bool = True
    burn_subtitles: bool = True
    platforms: list[str] = Field(default_factory=list)
    account: str = "default"
    publish_at: str | None = None
    publish: bool = False
    native_schedule: bool = False
    mock: bool = False


class PublishIn(BaseModel):
    platforms: list[str]
    account: str = "default"
    publish_at: str | None = None
    native_schedule: bool = False


class LoginIn(BaseModel):
    account: str = "default"
    headed: bool | None = None


def _settings(request: Request) -> Settings:
    override = getattr(request.app.state, "settings_override", None)
    if override is not None:
        return override
    return load_settings()


def _http_error(exc: ReelPressError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


class LoginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}

    def start(self, settings: Settings, platform: str, account: str, headed: bool | None) -> str:
        session_id = uuid.uuid4().hex[:12]
        record = {
            "id": session_id,
            "platform": platform,
            "account": account,
            "status": "waiting",
            "error": "",
        }
        with self._lock:
            self._sessions[session_id] = record
        thread = threading.Thread(
            target=self._run,
            args=(session_id, settings, platform, account, headed),
            daemon=True,
        )
        thread.start()
        return session_id

    def get(self, session_id: str) -> dict | None:
        with self._lock:
            record = self._sessions.get(session_id)
            return dict(record) if record else None

    def _run(self, session_id: str, settings: Settings, platform: str, account: str, headed: bool | None) -> None:
        qr_path = settings.data_dir / "login" / f"{session_id}.png"

        def on_qr(png: bytes) -> None:
            qr_path.parent.mkdir(parents=True, exist_ok=True)
            qr_path.write_bytes(png)
            with self._lock:
                self._sessions[session_id]["status"] = "waiting"

        try:
            uploader = get_uploader(platform)
            uploader.login(settings, account, on_qr=on_qr, headed=headed)
        except ReelPressError as exc:
            with self._lock:
                self._sessions[session_id]["status"] = "error"
                self._sessions[session_id]["error"] = str(exc)
            return
        except Exception as exc:
            with self._lock:
                self._sessions[session_id]["status"] = "error"
                self._sessions[session_id]["error"] = f"登录失败：{exc}"
            return
        with self._lock:
            self._sessions[session_id]["status"] = "success"
            self._sessions[session_id]["error"] = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = app.state.settings_override or load_settings()
        current.ensure_dirs()
        store = JobStore(current.db_path)
        runner = JobRunner(store, lambda: app.state.settings_override or load_settings())
        app.state.store = store
        app.state.runner = runner
        app.state.logins = LoginManager()
        runner.start()
        yield
        runner.shutdown()
        store.close()

    app = FastAPI(title="映流 ReelPress", version=__version__, lifespan=lifespan)
    app.state.settings_override = settings
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "ffmpeg": has_ffmpeg()}

    @app.get("/api/settings")
    def read_settings(request: Request) -> dict:
        return public_settings(_settings(request))

    @app.put("/api/settings")
    def write_settings(request: Request, payload: dict) -> dict:
        try:
            if request.app.state.settings_override is not None:
                raise ReelPressError("当前进程使用了固定配置，不能从页面写入。")
            updated = save_user_settings(payload, _settings(request))
        except ReelPressError as exc:
            raise _http_error(exc) from exc
        return public_settings(updated)

    @app.get("/api/platforms")
    def platforms(request: Request, account: str = "default") -> dict:
        settings = _settings(request)
        rows = []
        for item in list_platforms():
            logged = False
            try:
                logged = bool(get_uploader(item["name"]).check(settings, account, live=False))
            except ReelPressError:
                logged = False
            rows.append({**item, "logged_in": logged, "account": account})
        return {"account": account, "platforms": rows}

    @app.post("/api/platforms/{name}/login")
    def start_login(name: str, body: LoginIn, request: Request) -> dict:
        settings = _settings(request)
        if name == "youtube":
            raise HTTPException(status_code=400, detail="YouTube 请使用 OAuth 授权，不使用二维码。")
        try:
            get_uploader(name)
        except ReelPressError as exc:
            raise _http_error(exc) from exc
        session_id = request.app.state.logins.start(settings, name, body.account, body.headed)
        return {"session_id": session_id, "status": "waiting"}

    @app.get("/api/platforms/login/{session_id}")
    def login_status(session_id: str, request: Request) -> dict:
        record = request.app.state.logins.get(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="登录会话不存在。")
        record["qr"] = f"/api/platforms/login/{session_id}/qr"
        return record

    @app.get("/api/platforms/login/{session_id}/qr")
    def login_qr(session_id: str, request: Request) -> FileResponse:
        settings = _settings(request)
        path = settings.data_dir / "login" / f"{session_id}.png"
        if not path.exists():
            raise HTTPException(status_code=404, detail="二维码还没准备好。")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/platforms/{name}/check")
    def check_platform(name: str, request: Request, account: str = "default", live: bool = False) -> dict:
        settings = _settings(request)
        try:
            ok = get_uploader(name).check(settings, account, live=live)
        except ReelPressError as exc:
            raise _http_error(exc) from exc
        return {"platform": name, "account": account, "logged_in": ok}

    @app.get("/api/oauth/youtube/start")
    def youtube_start(request: Request, account: str = "default") -> RedirectResponse:
        settings = _settings(request)
        state = secrets.token_urlsafe(18)
        settings.token_dir.mkdir(parents=True, exist_ok=True)
        (settings.token_dir / "oauth_state.json").write_text(
            json.dumps({"state": state, "account": account}),
            encoding="utf-8",
        )
        try:
            url = build_auth_url(settings, state)
        except ReelPressError as exc:
            raise _http_error(exc) from exc
        return RedirectResponse(url)

    @app.get("/api/oauth/youtube/callback")
    def youtube_callback(
        request: Request,
        code: str = "",
        state: str = "",
        error: str = "",
    ) -> RedirectResponse:
        settings = _settings(request)
        if error:
            return RedirectResponse(f"/?youtube=error&message={quote(error)}")
        state_path = settings.token_dir / "oauth_state.json"
        if not state_path.exists():
            raise HTTPException(status_code=400, detail="授权状态丢失，请重新发起。")
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        if not state or saved.get("state") != state:
            raise HTTPException(status_code=400, detail="授权 state 不匹配。")
        try:
            exchange_code(settings, code, account=saved.get("account") or "default")
        except ReelPressError as exc:
            raise _http_error(exc) from exc
        return RedirectResponse("/?youtube=ok")

    @app.get("/api/jobs")
    def list_jobs(request: Request) -> dict:
        jobs = request.app.state.store.list()
        return {"jobs": [job.to_dict() for job in jobs]}

    @app.post("/api/jobs")
    def create_job(body: JobIn, request: Request) -> dict:
        params = GenerateParams(
            topic=body.topic.strip(),
            script=body.script.strip(),
            aspect=body.aspect,
            voice=body.voice.strip(),
            rate=body.rate.strip(),
            stock_provider=body.stock_provider.strip(),
            bgm=body.bgm,
            burn_subtitles=body.burn_subtitles,
            platforms=body.platforms,
            account=body.account.strip() or "default",
            publish_at=body.publish_at,
            publish=body.publish or bool(body.platforms),
            native_schedule=body.native_schedule,
            mock=body.mock,
        )
        if not params.topic and not params.script and not params.mock:
            raise HTTPException(status_code=400, detail="请填写主题，或直接粘贴口播文案。")
        try:
            job = request.app.state.store.create(params)
        except ReelPressError as exc:
            raise _http_error(exc) from exc
        request.app.state.runner.submit(job.id)
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str, request: Request) -> dict:
        job = request.app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return job.to_dict()

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, request: Request) -> dict:
        store: JobStore = request.app.state.store
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        if job.status in ACTIVE:
            raise HTTPException(status_code=409, detail="任务还在进行，不能删除。")
        store.delete(job_id)
        directory = _settings(request).jobs_dir / job_id
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/video")
    def job_video(job_id: str, request: Request) -> FileResponse:
        job = request.app.state.store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        raw = str(job.result.get("video_path") or "")
        if not raw:
            raise HTTPException(status_code=404, detail="成片还没准备好。")
        path = Path(raw).resolve()
        root = _settings(request).jobs_dir.resolve()
        if root != path and root not in path.parents:
            raise HTTPException(status_code=403, detail="不能读取任务目录以外的文件。")
        if not path.exists():
            raise HTTPException(status_code=404, detail="成片文件已丢失。")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.post("/api/jobs/{job_id}/publish")
    def publish(job_id: str, body: PublishIn, request: Request) -> dict:
        try:
            return schedule_or_publish(
                job_id,
                request.app.state.store,
                _settings(request),
                platforms=body.platforms,
                account=body.account,
                publish_at=body.publish_at,
                native_schedule=body.native_schedule,
            )
        except ReelPressError as exc:
            raise _http_error(exc) from exc

    return app
