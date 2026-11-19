"""Command line for generation, login, and the local web UI."""

from __future__ import annotations

import argparse
import json
import sys

from reelpress import __version__
from reelpress.config import load_settings, public_settings
from reelpress.errors import ReelPressError
from reelpress.jobs import JobRunner, JobStore
from reelpress.media import cjk_font_file, has_ffmpeg
from reelpress.models import GenerateParams
from reelpress.publish import schedule_or_publish
from reelpress.uploaders.registry import uploader_names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reelpress", description="映流：生成短视频并发布到各平台")
    parser.add_argument("--version", action="version", version=f"映流 {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="启动网页")
    serve.add_argument("--host", default="")
    serve.add_argument("--port", type=int, default=0)
    serve.set_defaults(func=cmd_serve)

    generate = sub.add_parser("generate", help="生成一条成片")
    generate.add_argument("--topic", default="")
    generate.add_argument("--script", default="")
    generate.add_argument("--aspect", default="", choices=["", "9:16", "16:9"])
    generate.add_argument("--voice", default="")
    generate.add_argument("--stock", default="", help="pexels、pixabay、ai 或 placeholder")
    generate.add_argument("--mock", action="store_true", help="不调用外部接口，用占位画面和静音时间轴")
    generate.add_argument("--no-subtitle", action="store_true")
    generate.add_argument("--no-bgm", action="store_true")
    generate.add_argument("--stop-at", default="video", choices=["script", "audio", "subtitle", "materials", "video"])
    generate.set_defaults(func=cmd_generate)

    jobs = sub.add_parser("jobs", help="查看任务")
    jobs.set_defaults(func=cmd_jobs)

    login = sub.add_parser("login", help="扫码登录一个平台")
    login.add_argument("platform", choices=[name for name in uploader_names() if name != "youtube"])
    login.add_argument("--account", default="default")
    login.add_argument("--headless", action="store_true")
    login.add_argument("--cdp-url", default="")
    login.set_defaults(func=cmd_login)

    check = sub.add_parser("check", help="检查登录态")
    check.add_argument("platform", choices=uploader_names())
    check.add_argument("--account", default="default")
    check.add_argument("--live", action="store_true", help="打开浏览器实际访问发布页")
    check.set_defaults(func=cmd_check)

    publish = sub.add_parser("publish", help="发布一条已完成的任务")
    publish.add_argument("--job", required=True)
    publish.add_argument("--platform", action="append", required=True)
    publish.add_argument("--account", default="default")
    publish.add_argument("--at", default="", help="本地定时，例如 2026-10-10T20:00")
    publish.add_argument("--native-schedule", action="store_true")
    publish.set_defaults(func=cmd_publish)

    doctor = sub.add_parser("doctor", help="检查本机依赖和密钥是否就绪")
    doctor.set_defaults(func=cmd_doctor)

    show = sub.add_parser("config", help="查看当前配置（密钥已打码）")
    show.set_defaults(func=cmd_config)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ReelPressError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"映流已启动：http://{host}:{port}")
    uvicorn.run(create_server(), host=host, port=port, log_level="info")
    return 0


def create_server():
    from reelpress.web.app import create_app

    return create_app()


def cmd_generate(args: argparse.Namespace) -> int:
    settings = load_settings()
    params = GenerateParams(
        topic=args.topic,
        script=args.script,
        aspect=args.aspect or settings.video_aspect,
        voice=args.voice,
        stock_provider=args.stock,
        bgm=not args.no_bgm,
        burn_subtitles=not args.no_subtitle,
        mock=args.mock,
        stop_at=args.stop_at,
    )
    store = JobStore(settings.db_path)
    runner = JobRunner(store, lambda: settings)
    try:
        job = store.create(params)
        print(f"任务 {job.id} 开始生成……")
        runner._execute(job.id)
        done = store.get(job.id)
    finally:
        store.close()
    if done is None:
        return 1
    if done.status == "failed":
        print(f"错误：{done.error}", file=sys.stderr)
        return 1
    print(json.dumps(done.to_dict(), ensure_ascii=False, indent=2))
    video = done.result.get("video_path")
    if video:
        print(f"成片：{video}")
    return 0


def cmd_jobs(_args: argparse.Namespace) -> int:
    settings = load_settings()
    store = JobStore(settings.db_path)
    rows = store.list(limit=30)
    store.close()
    if not rows:
        print("还没有任务。")
        return 0
    for job in rows:
        print(f"{job.id}  {job.status:<16} {job.progress:>3}%  {job.topic}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    from reelpress.uploaders.registry import get_uploader

    settings = load_settings()
    print(f"正在打开{args.platform}登录页。请用手机扫码，成功后会自动保存登录态。")
    path = get_uploader(args.platform).login(
        settings,
        args.account,
        headed=not args.headless,
        cdp_url=args.cdp_url,
    )
    print(f"已保存登录态：{path}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from reelpress.uploaders.registry import get_uploader

    settings = load_settings()
    ok = get_uploader(args.platform).check(settings, args.account, live=args.live)
    print("登录有效。" if ok else "未登录或登录态已过期。")
    return 0 if ok else 2


def cmd_publish(args: argparse.Namespace) -> int:
    settings = load_settings()
    store = JobStore(settings.db_path)
    result = schedule_or_publish(
        args.job,
        store,
        settings,
        platforms=args.platform,
        account=args.account,
        publish_at=args.at or None,
        native_schedule=args.native_schedule,
    )
    store.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"published", "scheduled"} else 1


def cmd_config(_args: argparse.Namespace) -> int:
    print(json.dumps(public_settings(load_settings()), ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    settings = load_settings()
    checks = [
        ("ffmpeg", has_ffmpeg(), "安装 ffmpeg 和 ffprobe"),
        ("中文字体", cjk_font_file() is not None, "安装 fonts-wqy-microhei 或其他中文字体"),
        ("大模型", settings.llm_configured(), "在配置里填写 llm.base_url / api_key / model"),
        ("Pexels", bool(settings.pexels_api_key), "可选。没有密钥时会使用占位画面"),
        ("Pixabay", bool(settings.pixabay_api_key), "可选"),
        ("AI 画面", bool(settings.visual_ai_base_url), "可选，填写 visual_ai.base_url"),
        ("YouTube 客户端", bool(settings.youtube_client_id and settings.youtube_client_secret), "发布到 YouTube 时需要"),
    ]
    try:
        import edge_tts  # noqa: F401

        checks.append(("edge-tts", True, ""))
    except ImportError:
        checks.append(("edge-tts", False, "pip install edge-tts"))
    try:
        import playwright  # noqa: F401

        checks.append(("playwright", True, ""))
    except ImportError:
        checks.append(("playwright", False, "pip install 'reelpress[upload]' && playwright install chromium"))

    failed = False
    for name, ok, hint in checks:
        mark = "就绪" if ok else "缺失"
        extra = "" if ok or not hint else f"  → {hint}"
        print(f"[{mark}] {name}{extra}")
        if name in {"ffmpeg", "中文字体", "edge-tts"} and not ok:
            failed = True
    print(f"数据目录：{settings.data_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
