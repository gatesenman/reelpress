# 映流 ReelPress

映流把一条短视频从选题做到成片，再发到抖音、快手、小红书、哔哩哔哩和 YouTube。

你给一个主题，或者直接贴口播。它会写标题、简介和标签，用语音合成配音，按口播对齐字幕，找来素材，用 ffmpeg 合成竖屏或横屏成片，并按你的安排发布。密钥只来自配置文件或环境变量，不会写进代码。

## 借鉴了什么

实现是新写的，结构参考了三个常用项目里已经验证过的做法：

| 项目 | 借来的想法 |
| --- | --- |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 分阶段流水线：文案 → 检索词 → 配音 → 字幕 → 素材 → 合成。每个任务单独落盘中间文件，可以用 `--stop-at` 停在某一阶段。画幅、配音、素材都由配置驱动。 |
| [ShortGPT](https://github.com/RayVentura/ShortGPT) | 语音和模型都是可替换的模块。默认用 Edge TTS，图库走 Pexels，另外留一个 AI 画面接口。 |
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | 每个平台一个发布器。中文平台用 Playwright 保存 `storage_state`，扫码登录，支持用 CDP 附着真实 Chrome。统一的 `login` / `check` / `publish` 动作。 |

YouTube 不走浏览器。按官方 [YouTube Data API v3](https://developers.google.com/youtube/v3) 做 OAuth 和断点续传。定时发布在本机队列里等到点再发；YouTube 也可以改成上传时带 `status.publishAt`。

## 架构

```text
网页 / CLI
    │
    ▼
任务队列（SQLite，一次生成一条）
    │
    ▼
文案 LLM ── 配音 TTS ── 字幕 SRT/ASS ── 素材 ── ffmpeg 合成
    │                                      │
    │                                      ├─ Pexels / Pixabay
    │                                      ├─ 可选 AI 画面接口
    │                                      └─ 无密钥时的占位画面
    ▼
发布器
    ├─ YouTubeUploader        OAuth + videos.insert
    └─ BrowserUploader        抖音 / 快手 / 小红书 / 哔哩哔哩
```
新增平台时实现 `Uploader`（`check`、`login`、`upload`），并在 `src/reelpress/uploaders/registry.py` 注册。浏览器平台多数只需要补一份 `PlatformSpec`：登录地址、上传地址、登录 cookie 名和页面选择器。

任务目录在 `data/jobs/<id>/`，里面有 `script.json`、`audio.mp3` 或 `audio.m4a`、`subtitle.srt`、`subtitle.ass` 和 `final.mp4`。

## 环境

- Python 3.11 及以上
- ffmpeg、ffprobe
- 一种中文字体。Debian/Ubuntu 用 `fonts-wqy-microhei`，否则字幕里的汉字会是方框
- 发布到中文平台时再加 Playwright Chromium

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,upload]"
playwright install chromium
cp config.example.toml config.toml
reelpress doctor
reelpress serve
```
浏览器打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。

没有密钥时，可以先点网页上的「离线演示一条」，或者：

```bash
reelpress generate --mock --topic "清晨的街道"
```
离线演示不调用大模型和语音服务，用静音时间轴和占位画面合成一条真的 mp4，用来确认 ffmpeg 和字幕正常。正式成片不要用这个模式。

## 配置

优先级：环境变量 > `data/settings.json`（网页保存的）> `config.toml` > 内置默认值。

环境变量为空字符串时忽略，避免 Docker 里没填的变量把配置文件清掉。网页返回的密钥只有打码后的提示。`config.toml` 已在 `.gitignore` 里。

对应关系：

| 环境变量 | 配置 |
| --- | --- |
| `REELPRESS_LLM_BASE_URL` | `llm.base_url` |
| `REELPRESS_LLM_API_KEY` | `llm.api_key` |
| `REELPRESS_LLM_MODEL` | `llm.model` |
| `REELPRESS_PEXELS_API_KEY` | `stock.pexels_api_key` |
| `REELPRESS_PIXABAY_API_KEY` | `stock.pixabay_api_key` |
| `REELPRESS_VISUAL_AI_BASE_URL` | `visual_ai.base_url` |
| `REELPRESS_VISUAL_AI_API_KEY` | `visual_ai.api_key` |
| `REELPRESS_YOUTUBE_CLIENT_ID` | `youtube.client_id` |
| `REELPRESS_YOUTUBE_CLIENT_SECRET` | `youtube.client_secret` |
| `REELPRESS_TTS_VOICE` | `tts.voice` |
| `REELPRESS_UPLOAD_CDP_URL` | `upload.cdp_url` |
| `REELPRESS_DATA_DIR` | `app.data_dir` |
| `REELPRESS_CONFIG` | 配置文件路径 |

没有配大模型、但自己贴了口播时，标题和检索词用本地规则生成，任务里会有一条警告。两者都没有时，任务直接失败并说明缺什么。没有图库密钥时，自动改用占位画面，成片仍然能导出。

### 大模型

任何 OpenAI 兼容的 `/chat/completions` 都可以。在 `config.toml` 里改 `base_url` 和 `model`：

```toml
[llm]
# DeepSeek
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key = ""

# 通义千问
# base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# model = "qwen-plus"

# Grok
# base_url = "https://api.x.ai/v1"
# model = "grok-3"

# 本机兼容服务可以不填 api_key，只要 base_url 不是默认的 OpenAI 地址
# base_url = "http://127.0.0.1:11434/v1"
# model = "qwen2.5"
```
密钥也可以只放在环境变量 `REELPRESS_LLM_API_KEY`，不写进文件。

### Pexels

1. 打开 [https://www.pexels.com/api/](https://www.pexels.com/api/) 申请 API Key。
2. 填到 `stock.pexels_api_key` 或 `REELPRESS_PEXELS_API_KEY`。
3. `stock.provider` 设为 `pexels`。竖屏会按 `portrait` 检索，横屏按 `landscape`。

素材受 Pexels 许可协议约束，发布前自己确认能否用于商业用途。

### Pixabay

1. 在 [https://pixabay.com/api/docs/](https://pixabay.com/api/docs/) 申请 Key。
2. 填到 `stock.pixabay_api_key`，并把 `stock.provider` 改为 `pixabay`。

### AI 画面接口

这是一个可选钩子，映流不绑定任何一家图像或视频模型。把 `stock.provider` 设为 `ai`，并配置：

```toml
[visual_ai]
base_url = "https://your-service.example"
api_key = ""
model = "your-model"
```
映流会对每个检索词发送：

```http
POST {base_url}/v1/videos
Authorization: Bearer {api_key}
Content-Type: application/json

{"prompt": "rainy street", "aspect": "9:16", "duration": 4, "model": "your-model"}
```
响应二选一：

```json
{"url": "https://cdn.example/clip.mp4"}
```
```json
{"b64": "<mp4 的 base64>"}
```
返回的文件会进入和素材库相同的合成流程。接口失败时会退回占位画面，并在任务警告里写明原因。

### 配音

默认是 [edge-tts](https://github.com/rany2/edge-tts)，不需要密钥，但机器要能访问微软语音服务。常用中文声音：

- `zh-CN-XiaoxiaoNeural` 晓晓
- `zh-CN-XiaoyiNeural` 晓伊
- `zh-CN-YunxiNeural` 云希
- `zh-CN-YunjianNeural` 云健
- `zh-CN-YunyangNeural` 云扬

要换别的引擎，实现 `TTSProvider.synthesize(text, output, voice, rate) -> list[Cue]`，在 `reelpress.tts.build_tts` 里挂上名字，再把 `tts.provider` 改成那个名字。`estimated` 是测试和离线演示用的静音时间轴。

语速示例：`tts.rate = "+10%"`。

### 背景音乐

把 mp3、m4a 或 wav 放进 `data/music/`。生成时会循环混到配音下面，音量由 `video.bgm_volume` 控制（默认 0.14）。目录为空就只保留人声。请只使用你有权使用的音乐。

### YouTube

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，创建项目。
2. 启用 **YouTube Data API v3**。
3. 创建 OAuth 客户端，类型选「桌面应用」或「Web 应用」。
4. 把下面这个回调地址加进已获授权的重定向 URI：

   `http://127.0.0.1:8765/api/oauth/youtube/callback`

5. 把客户端 ID、密钥分别填进 `youtube.client_id`、`youtube.client_secret`，或环境变量 `REELPRESS_YOUTUBE_CLIENT_ID`、`REELPRESS_YOUTUBE_CLIENT_SECRET`。
6. 网页「发布账号」里点「前往 Google 授权」，或在浏览器打开：

   `http://127.0.0.1:8765/api/oauth/youtube/start`

令牌保存在 `data/tokens/youtube_<账号>.json`，权限是 `youtube.upload`。上传使用断点续传。选了定时并且勾了「交给平台定时」时，视频会以 `private` 上传并设置 `status.publishAt`，到点由 YouTube 公开。

未通过 Google 验证的 OAuth 应用，上传的视频可能被强制为私享，审核通过前不能改成公开。这是 Google 的限制，不是本工具能绕过的。个人频道如果只是自己用，通常仍可以在 YouTube Studio 里看到这条视频。

## 平台登录

中文平台没有稳定的个人开发者上传 API。映流用 Playwright 打开创作者后台，等你扫码，然后把登录态写成 Playwright 的 `storage_state`：

```text
data/cookies/<平台>_<账号名>.json
```
账号名默认 `default`。给同一个平台保存多个号时，用不同的账号名。

网页：打开「发布账号」，填写账号名，点「扫码登录」。二维码出现后用对应 App 扫描。

命令行：

```bash
reelpress login douyin --account shop
reelpress check douyin --account shop
reelpress login kuaishou --account shop
reelpress login xiaohongshu --account shop
reelpress login bilibili --account shop
```
登录默认打开有头浏览器。服务器上没有显示器时，扫码经常被判为异常，这时改用本机 Chrome：

```bash
# macOS / Linux。Windows 把路径换成 chrome.exe
google-chrome --remote-debugging-port=9222
reelpress login douyin --account shop --cdp-url http://127.0.0.1:9222
```
也可以把地址写进 `upload.cdp_url`。CDP 模式下映流不会关闭你已经打开的浏览器。

各平台入口：

| 平台 | 登录页 | 上传页 | 用来判断登录的 cookie |
| --- | --- | --- | --- |
| 抖音 | `https://creator.douyin.com/` | `/creator-micro/content/upload` | `sessionid` |
| 快手 | `https://cp.kuaishou.com/` | `/article/publish/video` | `userId`、`kuaishou.web.cp.api_st` |
| 小红书 | `https://creator.xiaohongshu.com/login` | `/publish/publish` | `customer-sso-sid`、`galaxy_creator_session_id` |
| 哔哩哔哩 | `https://passport.bilibili.com/login` | 投稿页 `/platform/upload/video/frame` | `SESSDATA` |

`check` 默认只看本地 cookie 是否过期。加 `--live` 会真正打开上传页再确认一次。

上传流程是：打开上传页、把成片交给 `input[type=file]`、填写标题和简介、点击发布。选择器写在 `src/reelpress/uploaders/platforms.py`。网站改版后如果提示找不到标题或发布按钮，更新对应的 `title_selectors` / `publish_selectors` 即可，不必改流水线。

这些自动化只应用于你自己拥有的账号。

## 命令

```bash
reelpress serve --host 127.0.0.1 --port 8765
reelpress doctor
reelpress config

reelpress generate --topic "下班后的十分钟" --aspect 9:16
reelpress generate --topic "城市夜跑" --script "今晚只跑十分钟。" --stock pexels
reelpress generate --topic "草稿" --stop-at script

reelpress jobs
reelpress publish --job <任务ID> --platform douyin --platform youtube --account shop
reelpress publish --job <任务ID> --platform douyin --at 2026-10-10T20:00
reelpress publish --job <任务ID> --platform youtube --at 2026-10-10T20:00 --native-schedule
```
`--stop-at` 可以是 `script`、`audio`、`subtitle`、`materials`、`video`。

网页上勾选「生成后发布」会在成片完成后继续。填了本地时间就先进入「待发布」，到点由本机队列上传。服务进程得开着，定时才会触发。

「交给平台定时」时，YouTube 使用 `publishAt`。抖音等平台只会尝试点击页面上的「定时发布」，点不到就在任务里报错。更稳妥的是用本机定时。

## Docker

```bash
cp .env.example .env
# 编辑 .env，至少填 REELPRESS_LLM_API_KEY
docker compose up --build
```
容器监听 `8765`，数据在 `./data`（登录态、任务、设置都在这里）。镜像里包含 ffmpeg、文泉驿微米黑和 Playwright Chromium。

YouTube 回调地址必须和浏览器实际访问的地址一致。如果不是本机的 `127.0.0.1:8765`，请同时改 Google 控制台和 `youtube.redirect_uri`。

只用配置文件、不用环境变量时，在 `docker-compose.yml` 里取消 `config.toml` 那一行的注释。不要把写有密钥的 `config.toml` 提交到仓库。

## 测试

```bash
pip install -e ".[dev]"
pytest
```
测试不访问外网。大模型、Pexels、YouTube 用 `httpx.MockTransport`。抖音上传用假的浏览器会话，检查标题是否填入、发布按钮是否点击。另有一条真的 ffmpeg 流水线：静音配音、占位画面、烧录字幕，断言成片里同时有视频轨和音频轨。

## 目录

```text
src/reelpress/
  cli.py            命令行
  config.py         配置合并
  pipeline.py       阶段编排
  llm.py            OpenAI 兼容文案
  tts.py            edge-tts 与静音时间轴
  subtitles.py      SRT / ASS
  materials.py      Pexels、Pixabay、AI 钩子、占位画面
  compose.py        ffmpeg 合成
  jobs.py           SQLite 队列与定时线程
  publish.py        立即发布或等到点
  uploaders/        YouTube 与浏览器发布器
  web/              FastAPI 与中文界面
```
## 限制

- 抖音、快手、小红书、哔哩哔哩的页面选择器会过期。上传失败时，错误会写明缺的是标题框还是发布按钮。
- 无头浏览器容易被识别。二维码可能显示「异常」或扫了没有登录态。优先使用有头模式，或用 `--cdp-url` 附着日常使用的 Chrome。平台风控、验证码、掉登录、限制投稿，都可能发生，严重时账号会受到限制。不要用它操作不属于你的账号，也不要高频群发。
- 哔哩哔哩这里走的是网页投稿，不是 biliup 命令行。分区、转载声明等额外表单没有逐项填写，投稿页如果强制要求这些字段，需要按页面补选择器。
- Edge TTS 依赖微软的在线服务，没有服务等级协议，声音列表也会变。
- 图库检索词由模型生成英文。模型跑偏时，画面会和口播不相关。可以改成 `placeholder`，或换 AI 画面接口。
- YouTube 未验证的 API 项目可能只能得到私享视频。
- 定时发布依赖映流进程一直运行。本机队列不会在关机后自动补发，重新打开后，到点的任务会在几秒内被拾起。
- 合成使用 ffmpeg（libx264、aac、libass）。没有把 MoviePy 放进依赖，避免再包一层同样调用 ffmpeg 的运行时。
- 一次只生成一条成片。这是短视频合成的耗时决定的，不是漏做的队列。

## 许可

MIT，见 [LICENSE](LICENSE)。平台页面、素材网站和 YouTube API 各自的使用条款仍然适用。
