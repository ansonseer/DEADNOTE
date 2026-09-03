"""模型路由：任务 → provider，附带 schema 校验、一次纠错重试、成本记录。

这是"Agent 的分工表"落地的地方：改 config/models.yaml 即可换模型，不动代码。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from ..schemas import BY_TASK, SchemaError, coerce, validate
from .providers import BaseProvider, MockProvider, ProviderError, build_provider, provider_available


class Router:
    def __init__(self, settings, conn=None, force_mock: bool | None = None, verbose: bool = False):
        self.settings = settings
        self.conn = conn
        self.verbose = verbose
        self.force_mock = force_mock if force_mock is not None else os.environ.get("PF_MOCK") == "1"
        self._cache: dict[str, BaseProvider] = {}
        self.last_citations: list[str] = []   # 最近一次调用里模型联网拿到的来源 URL

    # ---- 选择 provider ----
    def provider_name_for(self, task: str) -> str:
        if self.force_mock:
            return "mock"
        cfg = self.settings.models
        providers = cfg.get("providers", {})
        preferred = cfg.get("routing", {}).get(task, "anthropic")
        order = [preferred] + [p for p in cfg.get("fallback_order", []) if p != preferred]
        for name in order:
            if name in providers and provider_available(name, providers[name]):
                return name
        return "mock"

    def provider_for(self, task: str) -> BaseProvider:
        name = self.provider_name_for(task)
        if name not in self._cache:
            cfg = self.settings.models.get("providers", {}).get(name, {"kind": "mock"})
            try:
                self._cache[name] = build_provider(name, cfg)
            except Exception as e:  # SDK 没装 / key 不对 → 退回 mock，但把原因打出来
                if self.verbose:
                    print(f"[router] provider {name} 不可用（{e}），退回 mock")
                self._cache[name] = MockProvider()
        return self._cache[name]

    def is_mock(self, task: str) -> bool:
        return self.provider_name_for(task) == "mock"

    def supports_search(self, task: str) -> bool:
        """这个任务落到的模型能不能自己联网（Kimi $web_search / 智谱 web_search / Claude web_search）。"""
        return bool(getattr(self.provider_for(task), "supports_search", False))

    # ---- 调用 ----
    def call(self, task: str, system: str, user: str, *, context: dict | None = None,
             web_search: bool = False, retries: int = 1) -> dict:
        schema = BY_TASK[task]
        provider = self.provider_for(task)
        user_msg = user + "\n\n【输出要求】只输出一个 JSON 对象，严格符合以下 JSON Schema（不要多余字段）：\n" + \
            json.dumps(schema, ensure_ascii=False)
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            started = time.time()
            try:
                res = provider.complete_json(task, system, user_msg, schema, context=context, web_search=web_search)
                data = coerce(res.data, schema)
                validate(data, schema)
                self.last_citations = list(res.citations)
                self._log(task, provider, res.input_tokens, res.output_tokens, time.time() - started, True, None)
                if self.verbose:
                    print(f"[router] {task} ← {provider.name}/{provider.model} ok ({res.input_tokens}+{res.output_tokens} tok)")
                return data
            except SchemaError as e:
                last_err = e
                self._log(task, provider, 0, 0, time.time() - started, False, f"schema: {e}")
                user_msg = user_msg + f"\n\n【上一次输出未通过校验】{e}。请修正后重新输出完整 JSON。"
            except ProviderError as e:
                last_err = e
                self._log(task, provider, 0, 0, time.time() - started, False, str(e))
        raise ProviderError(f"{task} 调用失败：{last_err}")

    def _log(self, task, provider, in_tok, out_tok, seconds, ok, error):
        if self.conn is None:
            return
        from ..db import log_run
        log_run(self.conn, task=task, provider=provider.name, model=provider.model, input_tokens=in_tok,
                output_tokens=out_tok, seconds=round(seconds, 2), ok=1 if ok else 0, error=error)

    def describe(self) -> list[tuple[str, str, str]]:
        """给 `pf status` 用：每个任务实际会落到哪个 provider。"""
        out = []
        providers = self.settings.models.get("providers", {})
        for task in BY_TASK:
            name = self.provider_name_for(task)
            out.append((task, name, providers.get(name, {}).get("model", "mock")))
        return out
