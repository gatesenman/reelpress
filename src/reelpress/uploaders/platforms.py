"""Browser publishers for Douyin, Kuaishou, Xiaohongshu, and Bilibili.

Selectors are best-effort and will need updates when a creator site changes.
The local scheduler is the reliable way to publish later; native schedule
controls are optional and only clicked when native_schedule is set.
"""

from __future__ import annotations

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.models import UploadRequest, UploadResult
from reelpress.uploaders.base import cookie_path
from reelpress.uploaders.browser import (
    PlatformSpec,
    browser_call,
    fast_check,
    run_check,
    run_login,
    run_upload,
)

PLATFORM_SPECS: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        name="douyin",
        label="抖音",
        login_url="https://creator.douyin.com/",
        upload_url="https://creator.douyin.com/creator-micro/content/upload",
        cookie_names=("sessionid", "sessionid_ss"),
        title_selectors=(
            "input[placeholder*='填写作品标题']",
            "input[placeholder*='标题']",
            "input.semi-input",
        ),
        description_selectors=(
            "div[data-placeholder*='简介']",
            ".zone-container",
            "div[contenteditable='true']",
        ),
        publish_selectors=("button.button-primary",),
        publish_names=("发布",),
        schedule_selectors=("label:has-text('定时发布')",),
        max_title=30,
    ),
    PlatformSpec(
        name="kuaishou",
        label="快手",
        login_url="https://cp.kuaishou.com/",
        upload_url="https://cp.kuaishou.com/article/publish/video",
        cookie_names=("userId", "kuaishou.web.cp.api_st", "passToken"),
        title_selectors=(
            "input[placeholder*='标题']",
            "input[placeholder*='作品']",
        ),
        description_selectors=(
            "#work-description-edit",
            "div[contenteditable='true']",
            "textarea",
        ),
        publish_selectors=("button:has-text('发布')",),
        publish_names=("发布",),
        schedule_selectors=("label:has-text('定时发布')",),
        max_title=50,
    ),
    PlatformSpec(
        name="xiaohongshu",
        label="小红书",
        login_url="https://creator.xiaohongshu.com/login",
        upload_url="https://creator.xiaohongshu.com/publish/publish?from=menu&target=video",
        cookie_names=(
            "customer-sso-sid",
            "galaxy_creator_session_id",
            "access-token-creator.xiaohongshu.com",
        ),
        title_selectors=(
            "input[placeholder*='标题']",
            "input.d-text",
        ),
        description_selectors=(
            "div[contenteditable='true']",
            "#post-textarea",
            "textarea",
        ),
        publish_selectors=("button:has-text('发布')",),
        publish_names=("发布",),
        schedule_selectors=("label:has-text('定时发布')",),
        max_title=20,
    ),
    PlatformSpec(
        name="bilibili",
        label="哔哩哔哩",
        login_url="https://passport.bilibili.com/login",
        upload_url="https://member.bilibili.com/platform/upload/video/frame",
        cookie_names=("SESSDATA", "bili_jct"),
        title_selectors=(
            "input[placeholder*='标题']",
            ".video-title input",
            "input.input-val",
        ),
        description_selectors=(
            "div[contenteditable='true']",
            "textarea[placeholder*='简介']",
            "textarea",
        ),
        publish_selectors=("button:has-text('立即投稿')",),
        publish_names=("立即投稿",),
        schedule_selectors=("label:has-text('定时发布')",),
        max_title=80,
    ),
)

_BY_NAME = {spec.name: spec for spec in PLATFORM_SPECS}


def get_spec(name: str) -> PlatformSpec:
    spec = _BY_NAME.get(name)
    if spec is None:
        raise ReelPressError(f"没有名为 {name} 的浏览器发布器。")
    return spec


class BrowserUploader:
    method = "playwright"

    def __init__(self, spec: PlatformSpec, session_factory=None) -> None:
        self.spec = spec
        self.name = spec.name
        self.label = spec.label
        # Tests inject session_factory(cookie_file) -> BrowserSession.
        self.session_factory = session_factory

    def cookie_file(self, settings: Settings, account: str):
        return cookie_path(settings, self.name, account)

    def check(self, settings: Settings, account: str, *, live: bool = False) -> bool:
        path = self.cookie_file(settings, account)
        if not live:
            return fast_check(path, self.spec)
        if self.session_factory is not None:
            return run_check(self.session_factory(path if path.exists() else None), self.spec)
        return browser_call(
            self.spec,
            path,
            headed=not settings.upload_headless,
            cdp_url=settings.upload_cdp_url,
            action=lambda session: run_check(session, self.spec),
        )

    def login(
        self,
        settings: Settings,
        account: str,
        *,
        on_qr=None,
        headed: bool | None = None,
        cdp_url: str = "",
        timeout: int | None = None,
    ):
        path = self.cookie_file(settings, account)
        use_headed = (not settings.upload_headless) if headed is None else headed
        cdp = cdp_url or settings.upload_cdp_url
        limit = timeout or settings.login_timeout
        if self.session_factory is not None:
            session = self.session_factory(None)
            return run_login(session, self.spec, path, timeout=limit, on_qr=on_qr, sleep=lambda _s: None)
        return browser_call(
            self.spec,
            None,
            headed=use_headed,
            cdp_url=cdp,
            action=lambda session: run_login(session, self.spec, path, timeout=limit, on_qr=on_qr),
        )

    def upload(self, settings: Settings, request: UploadRequest) -> UploadResult:
        path = self.cookie_file(settings, request.account)
        if not fast_check(path, self.spec):
            raise ReelPressError(f"还没有可用的{self.label}登录态。请先扫码登录账号 {request.account}。")
        if self.session_factory is not None:
            session = self.session_factory(path)
            return run_upload(session, self.spec, request, sleep=lambda _s: None)
        try:
            return browser_call(
                self.spec,
                path,
                headed=not settings.upload_headless,
                cdp_url=settings.upload_cdp_url,
                action=lambda session: run_upload(session, self.spec, request),
            )
        except ReelPressError:
            raise
        except Exception as exc:
            raise ReelPressError(f"{self.label}发布失败：{exc}") from exc
