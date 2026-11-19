# 映流 ReelPress

**0.1.0** · 用大模型生成短视频，并发布到抖音、YouTube 等平台。

## 功能特性

- 从文案到短视频的生成流水线（详见 `src/reelpress/README.md`）。
- 可选上传能力（Playwright）。
- 提供 `reelpress` 命令行入口与 Web 静态资源。

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn
- edge-tts
- 可选 Playwright

## 从源码运行

源码在 `src/reelpress/`。`pyproject.toml` 声明包名为 reelpress、版本 0.1.0。

```bash
cd src/reelpress
pip install -e .
reelpress --help
# 开发依赖：pip install -e ".[dev]" 或 ".[upload]"
```

具体命令与配置见该目录 README。

## 文档

- [源码 README](src/reelpress/README.md)

## 许可证

`src/reelpress/pyproject.toml` 声明为 MIT。仓库根目录未附带 LICENSE 文件。

---

## English

# ReelPress

**0.1.0** · Generate short videos with large language models and publish them to platforms such as Douyin and YouTube.

## Features

- A pipeline from copy to short video (see `src/reelpress/README.md`).
- Optional upload support via Playwright.
- Ships a `reelpress` CLI entry point and web static assets.

## Tech stack

- Python 3.11+
- FastAPI + Uvicorn
- edge-tts
- 可选 Playwright

## Getting started

Source is under `src/reelpress/`. `pyproject.toml` declares package name `reelpress`, version 0.1.0.

```bash
cd src/reelpress
pip install -e .
reelpress --help
# Optional: pip install -e ".[dev]" or ".[upload]"
```

See that directory's README for commands and configuration.

## Documentation

- [源码 README](src/reelpress/README.md)

## License

`src/reelpress/pyproject.toml` declares MIT. There is no LICENSE file at the repository root.

