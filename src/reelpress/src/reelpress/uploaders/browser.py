"""Playwright login and upload flow, with a session interface tests can fake.

Login follows social-auto-upload: open the creator site, wait until a
session cookie appears (QR scan), then save Playwright storage_state.
Upload fills the first matching selector. Platform pages change often, so
failures name the missing control instead of pretending success.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from reelpress.errors import ReelPressError
from reelpress.models import UploadRequest, UploadResult
from reelpress.uploaders.base import cookie_file_valid

QrCallback = Callable[[bytes], None]


class BrowserSession(Protocol):
    def goto(self, url: str) -> None: ...

    def cookies(self) -> list[dict]: ...

    def screenshot(self) -> bytes: ...

    def save_storage(self, path: str) -> None: ...

    def set_files(self, path: str) -> None: ...

    def fill_any(self, selectors: tuple[str, ...], text: str) -> bool: ...

    def click_any(self, selectors: tuple[str, ...], text_names: tuple[str, ...] = ()) -> bool: ...

    def url(self) -> str: ...


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    label: str
    login_url: str
    upload_url: str
    cookie_names: tuple[str, ...]
    title_selectors: tuple[str, ...]
    description_selectors: tuple[str, ...]
    publish_selectors: tuple[str, ...]
    publish_names: tuple[str, ...]
    schedule_selectors: tuple[str, ...] = ()
    max_title: int = 30


def logged_in(cookies: list[dict], names: tuple[str, ...]) -> bool:
    now = time.time()
    for cookie in cookies:
        if cookie.get("name") not in names or not cookie.get("value"):
            continue
        expires = cookie.get("expires", -1)
        try:
            exp = float(expires)
        except (TypeError, ValueError):
            exp = -1
        if exp < 0 or exp > now:
            return True
    return False


def run_login(
    session: BrowserSession,
    spec: PlatformSpec,
    cookie_file: Path,
    *,
    timeout: float,
    on_qr: QrCallback | None = None,
    sleep=time.sleep,
) -> Path:
    session.goto(spec.login_url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if logged_in(session.cookies(), spec.cookie_names):
            cookie_file.parent.mkdir(parents=True, exist_ok=True)
            session.save_storage(str(cookie_file))
            return cookie_file
        if on_qr:
            on_qr(session.screenshot())
        sleep(1.0)
    raise ReelPressError(
        f"{spec.label}登录超时。请用手机扫码，或改用有头浏览器 / --cdp-url 附着本机 Chrome。"
        "无头浏览器经常被平台判定为异常二维码。"
    )


def run_upload(session: BrowserSession, spec: PlatformSpec, request: UploadRequest, *, sleep=time.sleep) -> UploadResult:
    if not Path(request.video_path).exists():
        raise ReelPressError("成片不存在，无法发布。")
    session.goto(spec.upload_url)
    if not logged_in(session.cookies(), spec.cookie_names):
        raise ReelPressError(f"{spec.label}登录态已失效，请重新扫码。")
    try:
        session.set_files(request.video_path)
    except Exception as exc:  # Playwright raises its own error types.
        raise ReelPressError(f"没能把视频交给{spec.label}的上传控件：{exc}") from exc

    title = request.title.strip()[: spec.max_title]
    description = request.description.strip()
    tags = " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in request.hashtags)
    body = f"{description}\n{tags}".strip()

    filled = False
    for _ in range(30):
        if session.fill_any(spec.title_selectors, title):
            filled = True
            break
        sleep(1.0)
    if not filled:
        raise ReelPressError(
            f"没有在{spec.label}发布页找到标题输入框。页面可能已改版，或视频仍在上传。"
        )
    if body:
        session.fill_any(spec.description_selectors, body)
    if request.native_schedule and request.schedule_at and spec.schedule_selectors:
        session.click_any(spec.schedule_selectors, ("定时发布",))
    if not session.click_any(spec.publish_selectors, spec.publish_names):
        raise ReelPressError(f"没有找到{spec.label}的发布按钮。")
    return UploadResult(
        platform=spec.name,
        success=True,
        message=f"已在{spec.label}点击发布。请到创作者中心确认审核状态。",
    )


def run_check(session: BrowserSession, spec: PlatformSpec) -> bool:
    session.goto(spec.upload_url)
    return logged_in(session.cookies(), spec.cookie_names)


class PlaywrightSession:
    """Adapter over a sync Playwright page. Imported only when a browser is launched."""

    def __init__(self, page) -> None:
        self.page = page

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

    def cookies(self) -> list[dict]:
        return list(self.page.context.cookies())

    def screenshot(self) -> bytes:
        return self.page.screenshot(type="png")

    def save_storage(self, path: str) -> None:
        self.page.context.storage_state(path=path)

    def set_files(self, path: str) -> None:
        field = self.page.locator("input[type='file']").first
        field.set_input_files(path, timeout=20000)

    def fill_any(self, selectors: tuple[str, ...], text: str) -> bool:
        for selector in selectors:
            loc = self.page.locator(selector)
            try:
                if loc.count() == 0:
                    continue
                target = loc.first
                target.click(timeout=1500)
                target.fill(text, timeout=3000)
                return True
            except Exception:
                continue
        return False

    def click_any(self, selectors: tuple[str, ...], text_names: tuple[str, ...] = ()) -> bool:
        for selector in selectors:
            loc = self.page.locator(selector)
            try:
                if loc.count() == 0:
                    continue
                loc.first.click(timeout=3000)
                return True
            except Exception:
                continue
        for name in text_names:
            try:
                self.page.get_by_role("button", name=name, exact=True).first.click(timeout=3000)
                return True
            except Exception:
                continue
        return False

    def url(self) -> str:
        return self.page.url


def launch_playwright(storage: Path | None, *, headed: bool, cdp_url: str):
    """Context manager yielding (playwright, browser, context, page, should_close)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ReelPressError(
            "未安装 Playwright。请执行 pip install 'reelpress[upload]' && playwright install chromium。"
        ) from exc

    manager = sync_playwright().start()
    should_close = True
    if cdp_url:
        browser = manager.chromium.connect_over_cdp(cdp_url)
        should_close = False
        if storage and storage.exists():
            context = browser.new_context(storage_state=str(storage))
        elif browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context()
    else:
        browser = manager.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        kwargs = {}
        if storage and storage.exists():
            kwargs["storage_state"] = str(storage)
        context = browser.new_context(**kwargs)
    page = context.new_page()
    return manager, browser, context, page, should_close


def close_playwright(manager, browser, should_close: bool) -> None:
    if should_close:
        try:
            browser.close()
        except Exception:
            pass
    try:
        manager.stop()
    except Exception:
        pass


def browser_call(spec: PlatformSpec, cookie_file: Path | None, headed: bool, cdp_url: str, action):
    storage = cookie_file if cookie_file and cookie_file.exists() else None
    manager, browser, _context, page, should_close = launch_playwright(storage, headed=headed, cdp_url=cdp_url)
    try:
        return action(PlaywrightSession(page))
    finally:
        close_playwright(manager, browser, should_close)


def fast_check(cookie_file: Path, spec: PlatformSpec) -> bool:
    return cookie_file_valid(cookie_file, spec.cookie_names)
