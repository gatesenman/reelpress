"""OpenAI-compatible chat client and short-video copy generation.

Any service that speaks /chat/completions works: OpenAI, DeepSeek, Qwen,
Grok, or a local server. Pass an httpx.Client in tests.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.models import CopyBundle

DEMO_SCRIPT = (
    "清晨的街道还没完全醒来。街角面包店刚打开灯，空气里有一点麦香。"
    "把这一小段路走完，今天就已经开始了。"
)

_SYSTEM = (
    "你是短视频编导。只输出一个 JSON 对象，不要 Markdown，不要解释。"
    "口播要口语化，适合中文配音，不要写分镜，不要写镜头号。"
)


def chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ReelPressError("大模型没有返回可解析的 JSON。") from None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ReelPressError("大模型没有返回可解析的 JSON。") from exc
    if not isinstance(data, dict):
        raise ReelPressError("大模型返回的 JSON 不是对象。")
    return data


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        client: httpx.Client | None = None,
        timeout: float = 90,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self._client = client
        self._timeout = timeout

    def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = client.post(chat_completions_url(self.base_url), headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ReelPressError(f"大模型接口请求失败：{exc}") from exc
        finally:
            if owns_client:
                client.close()
        if response.status_code >= 400:
            detail = response.text[:300]
            raise ReelPressError(f"大模型接口返回 {response.status_code}：{detail}")
        try:
            body = response.json()
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ReelPressError("大模型接口的响应格式无法识别。") from exc


def _as_str_list(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,，\s]+", value)
        items = [part.strip() for part in parts if part.strip()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = []
    if prefix:
        items = [item if item.startswith(prefix) else f"{prefix}{item.lstrip('#')}" for item in items]
    return items


def normalize_bundle(data: dict[str, Any], topic: str, script: str) -> CopyBundle:
    narration = script.strip() or str(data.get("script") or "").strip()
    if not narration:
        raise ReelPressError("没有得到口播文案。")
    title = str(data.get("title") or topic).strip() or topic
    description = str(data.get("description") or narration[:80]).strip()
    hashtags = _as_str_list(data.get("hashtags") or [], prefix="#")[:8]
    if not hashtags:
        hashtags = [f"#{topic.strip()[:12] or '短视频'}"]
    terms = _as_str_list(data.get("search_terms") or data.get("terms") or [])[:6]
    if not terms:
        terms = [topic.strip() or "cinematic b-roll"]
    return CopyBundle(
        title=title[:80],
        description=description[:500],
        hashtags=hashtags,
        script=narration,
        search_terms=terms,
    )


def offline_copy(topic: str, script: str, *, mock: bool = False) -> CopyBundle:
    narration = script.strip()
    warnings: list[str] = []
    if not narration:
        if mock:
            narration = DEMO_SCRIPT
            warnings.append("离线演示使用了内置文案，没有调用大模型。")
        else:
            raise ReelPressError(
                "未配置大模型接口。请填写口播文案，或在设置里填写 OpenAI 兼容的 Base URL、模型和 API Key。"
            )
    else:
        warnings.append("未调用大模型，标题、简介和检索词由本地规则生成。")
    label = topic.strip() or "晨间散步"
    return CopyBundle(
        title=label[:30],
        description=narration[:80],
        hashtags=[f"#{label[:12]}", "#短视频", "#映流"],
        script=narration,
        search_terms=[label, "cinematic lifestyle", "city street", "natural light", "close up hands"],
        warnings=warnings,
    )


def build_prompt(topic: str, script: str, aspect: str) -> str:
    locked = script.strip()
    lock_rule = "用户已提供口播，script 字段必须与用户原文完全一致，不要改写。" if locked else "请原创一段 80 到 160 个汉字的口播。"
    return (
        f"主题：{topic.strip() or '日常生活'}\n"
        f"画幅：{aspect}\n"
        f"用户口播：{locked or '（无）'}\n"
        f"{lock_rule}\n"
        "检索词用英文，方便在 Pexels / Pixabay 搜索实拍素材，5 个，具体、可视。\n"
        "JSON 字段：title, description, hashtags, script, search_terms。\n"
        "title 不超过 20 个汉字。description 不超过 80 个汉字。hashtags 为 4 个带 # 的中文标签。"
    )


def generate_copy(
    settings: Settings,
    topic: str,
    script: str,
    aspect: str,
    *,
    mock: bool = False,
    client: LLMClient | None = None,
) -> CopyBundle:
    if mock or not settings.llm_configured():
        return offline_copy(topic, script, mock=mock)
    llm = client or LLMClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        settings.llm_temperature,
    )
    raw = llm.complete(_SYSTEM, build_prompt(topic, script, aspect))
    bundle = normalize_bundle(extract_json(raw), topic, script)
    if script.strip():
        bundle.script = script.strip()
    return bundle
