"""模型 provider：把"调一个模型拿到一个 JSON"这件事抽象掉。

- AnthropicProvider   ：官方 anthropic SDK；结构化输出（output_config.format）；可选 web_search 服务端工具。
- OpenAICompatProvider：DeepSeek / Kimi(Moonshot) / Qwen(DashScope) 都提供 OpenAI 兼容接口，用 openai SDK 调。
- MockProvider        ：离线、确定性的假输出，用来把管道先跑通、写测试、演示。

所有 provider 只有一个方法 complete_json(...) -> LLMResult，上层不关心细节。
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: Any
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    citations: list[str] = field(default_factory=list)


def extract_json(text: str) -> Any:
    """从模型文本里抠出 JSON：容忍 ```json 围栏、前后废话。"""
    if text is None:
        raise ProviderError("模型没有返回文本")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as e:
            raise ProviderError(f"无法解析 JSON：{e}") from e
    raise ProviderError("输出里没有 JSON 对象")


class BaseProvider:
    name = "base"
    model = ""

    def complete_json(self, task: str, system: str, user: str, schema: dict, *,
                      context: dict | None = None, web_search: bool = False) -> LLMResult:
        raise NotImplementedError


class MockProvider(BaseProvider):
    name = "mock"
    model = "mock"

    def complete_json(self, task, system, user, schema, *, context=None, web_search=False) -> LLMResult:
        from .mock import mock_result
        data = mock_result(task, context or {})
        return LLMResult(data=data, text=json.dumps(data, ensure_ascii=False), provider="mock", model="mock")


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, cfg: dict):
        import anthropic  # 延迟导入：没装 SDK 也能用 mock 跑

        api_key = os.environ.get(cfg.get("api_key_env", "ANTHROPIC_API_KEY"))
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = cfg.get("model", "claude-opus-5")
        self.effort = cfg.get("effort", "high")
        self.max_tokens = int(cfg.get("max_tokens", 16000))
        self.fallbacks = cfg.get("fallbacks", "default")   # 设为 null 可关闭服务端 refusal 回退
        self.max_search_uses = int(cfg.get("max_search_uses", 8))

    def complete_json(self, task, system, user, schema, *, context=None, web_search=False) -> LLMResult:
        import anthropic

        started = time.time()
        messages: list[dict] = [{"role": "user", "content": user}]
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
        )
        if web_search:
            # 带服务端搜索时不用 format 约束（搜索结果块 + 引用与 format 不兼容），改为在 prompt 里要求 JSON
            kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": self.max_search_uses}]
        else:
            kwargs["output_config"]["format"] = {"type": "json_schema", "schema": schema}

        resp = None
        for _ in range(6):  # pause_turn：服务端工具跑久了会暂停，把内容接回去继续
            resp = self._create(dict(kwargs, messages=messages))
            if resp.stop_reason == "refusal":
                detail = getattr(resp, "stop_details", None)
                raise ProviderError(f"模型拒绝了这个请求：{getattr(detail, 'category', None)}")
            if resp.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": resp.content}]

        texts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        text = texts[-1] if (web_search and texts) else "".join(texts)
        citations: list[str] = []
        for b in resp.content:
            if getattr(b, "type", "") == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
                for r in b.content:
                    url = getattr(r, "url", None)
                    if url:
                        citations.append(url)
        usage = getattr(resp, "usage", None)
        return LLMResult(
            data=extract_json(text), text=text, provider=self.name, model=self.model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            seconds=time.time() - started, citations=citations,
        )

    def _create(self, kwargs: dict):
        """默认开启服务端 refusal 回退（beta）；接口不接受时自动退回普通调用。"""
        import anthropic

        if self.fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks=self.fallbacks, **kwargs
                )
            except (anthropic.BadRequestError, TypeError):
                pass
        return self.client.messages.create(**kwargs)


class OpenAICompatProvider(BaseProvider):
    """DeepSeek / Kimi / Qwen 等 OpenAI 兼容接口。"""

    def __init__(self, name: str, cfg: dict):
        from openai import OpenAI

        self.name = name
        api_key = os.environ.get(cfg["api_key_env"])
        if not api_key:
            raise ProviderError(f"缺少环境变量 {cfg['api_key_env']}")
        self.client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
        self.model = cfg["model"]
        self.json_mode = bool(cfg.get("json_mode", True))
        self.max_tokens = int(cfg.get("max_tokens", 4096))
        self.temperature = float(cfg.get("temperature", 0.2))

    def complete_json(self, task, system, user, schema, *, context=None, web_search=False) -> LLMResult:
        started = time.time()
        messages = [
            {"role": "system", "content": system + "\n\n你必须只输出一个 JSON 对象（json），不要输出其他内容。"},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = dict(model=self.model, messages=messages, temperature=self.temperature,
                                      max_tokens=self.max_tokens)
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as e:  # 某些模型不支持 response_format，去掉再试一次
            if "response_format" in kwargs:
                kwargs.pop("response_format")
                resp = self.client.chat.completions.create(**kwargs)
            else:
                raise ProviderError(str(e)) from e
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        return LLMResult(
            data=extract_json(text), text=text, provider=self.name, model=self.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            seconds=time.time() - started,
        )


def build_provider(name: str, cfg: dict) -> BaseProvider:
    kind = cfg.get("kind", name)
    if kind == "mock":
        return MockProvider()
    if kind == "anthropic":
        return AnthropicProvider(cfg)
    if kind == "openai_compat":
        return OpenAICompatProvider(name, cfg)
    raise ProviderError(f"未知 provider 类型：{kind}")


def provider_available(name: str, cfg: dict) -> bool:
    kind = cfg.get("kind", name)
    if kind == "mock":
        return True
    if not os.environ.get(cfg.get("api_key_env", "")):
        return False
    try:
        if kind == "anthropic":
            import anthropic  # noqa: F401
        elif kind == "openai_compat":
            import openai  # noqa: F401
    except ImportError:
        return False
    return True
