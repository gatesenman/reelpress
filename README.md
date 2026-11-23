# 映流 ReelPress

**0.1.0** · 用大模型生成短视频，并发布到抖音、YouTube 等平台。

## 功能特性

- 可选上传能力（Playwright）。
- 提供 `reelpress` 命令行入口与 Web 静态资源。

## 下载

本仓库目前没有已发布的 GitHub Release 安装包。请从源码运行。GitHub 自动生成的 Source code zip/tar 不算安装包。

## 界面截图

仓库里目前还没有已提交的真实产品界面截图（图标、logo 或品牌图不算）。请不要把下列预留路径当成已经存在的图片去引用（避免破链）。待在真实运行窗口中截取后放入：

- `docs/screenshots/01-workbench.png`
- `docs/screenshots/02-main-or-result.png`

截图说明必须写明操作系统、软件版本、是否示例/演示数据，以及是否在 Windows 安装后截取。

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn
- edge-tts
- 可选 Playwright

## 从源码运行

源码在仓库根目录。`pyproject.toml` 声明包名为 reelpress、版本 0.1.0。

```bash
pip install -e .
reelpress --help
# 开发依赖：pip install -e ".[dev]" 或 ".[upload]"
```
具体命令与配置见该目录 README。

## 文档

- [LICENSE](LICENSE)

## 贡献

欢迎通过 Issue 和 Pull Request 参与，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。参与时请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

`pyproject.toml` 声明为 MIT。许可证见根目录 `LICENSE`。

---

## English

# ReelPress

**0.1.0** · Generate short videos with large language models and publish them to platforms such as Douyin and YouTube.

## Features

- Optional upload support via Playwright.
- Ships a `reelpress` CLI entry point and web static assets.

## Downloads

This repository has no published GitHub Release installer. Run it from source. The automatic Source code zip/tar from GitHub is not an installer.

## Screenshots

No real product-window screenshot has been committed yet (icons, logos, and brand art do not count). Do not add markdown image links to the reserved paths below until the files exist (that would be a broken link). After a live capture, place:

- `docs/screenshots/01-workbench.png`
- `docs/screenshots/02-main-or-result.png`

Captions must state the OS, version, whether the data is sample/demo, and whether the shot was taken after a Windows install.

## Tech stack

- Python 3.11+
- FastAPI + Uvicorn
- edge-tts
- 可选 Playwright

## Getting started

Source is at the repository root. `pyproject.toml` declares package name `reelpress`, version 0.1.0.

```bash
pip install -e .
reelpress --help
# Optional: pip install -e ".[dev]" or ".[upload]"
```
See that directory's README for commands and configuration.

## Documentation

- [LICENSE](LICENSE)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities privately via [SECURITY.md](SECURITY.md). This project follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

`pyproject.toml` declares MIT. See the `LICENSE` file at the repository root.
