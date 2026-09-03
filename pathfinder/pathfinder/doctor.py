"""pf doctor：一键体检。不改任何数据，只回答四个问题：
1) 哪些 key 配了、每个任务会落到哪个模型；
2) 配置里的模型 ID 在该平台是否存在（列 /models）；
3) 每个可用 provider 能不能返回一个合法 JSON；
4) 会联网的 provider 能不能真的搜到带 URL 的结果（--search）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from .llm.providers import ProviderError, build_provider, provider_available
from .schemas import coerce, validate

PING_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "model_says": {"type": "string"}},
               "required": ["ok", "model_says"], "additionalProperties": False}
SEARCH_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "date": {"type": "string"}},
                 "required": ["title", "url", "date"], "additionalProperties": False}


def list_models(cfg: dict) -> list[str] | str:
    """OpenAI 兼容的 GET /models；平台不支持时返回说明字符串。"""
    base = (cfg.get("base_url") or "").rstrip("/")
    key = os.environ.get(cfg.get("api_key_env", ""), "")
    if not base or not key:
        return "无 base_url 或 key"
    req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return sorted(m.get("id", "") for m in data.get("data", []))
    except Exception as e:  # 404 / 403 / 网络
        return f"无法列出（{type(e).__name__}: {str(e)[:80]}）"


def check_provider(name: str, cfg: dict, do_search: bool) -> dict:
    row = {"provider": name, "model": cfg.get("model", ""), "key": "✓" if provider_available(name, cfg) else "✗ 缺 key",
           "models": "", "json": "", "search": ""}
    if row["key"] != "✓" or cfg.get("kind") == "mock":
        return row
    if cfg.get("kind") == "openai_compat":
        models = list_models(cfg)
        if isinstance(models, list):
            row["models"] = ("✓ 存在" if cfg.get("model") in models else f"✗ 不在列表：{', '.join(models[:8])}{'…' if len(models) > 8 else ''}")
        else:
            row["models"] = models
    try:
        provider = build_provider(name, cfg)
    except Exception as e:
        row["json"] = f"✗ 初始化失败：{str(e)[:80]}"
        return row
    started = time.time()
    try:
        res = provider.complete_json("doctor", "你是体检程序。", "请只输出 JSON：{\"ok\": true, \"model_says\": \"<你的模型名>\"}",
                                     PING_SCHEMA)
        data = coerce(res.data, PING_SCHEMA)
        validate(data, PING_SCHEMA)
        row["json"] = f"✓ {time.time() - started:.1f}s，{res.input_tokens}+{res.output_tokens} tok，自称 {data.get('model_says', '')[:30]}"
    except (ProviderError, Exception) as e:
        row["json"] = f"✗ {type(e).__name__}: {str(e)[:120]}"
        return row
    if do_search and getattr(provider, "supports_search", False):
        started = time.time()
        try:
            res = provider.complete_json(
                "doctor", "你是体检程序，必须使用联网搜索工具查证后作答。",
                "搜索『阿里云 百炼 大模型 平台』最近 90 天内的一条公开新闻或官方公告，只输出 JSON：{\"title\": 标题, \"url\": 链接, \"date\": \"YYYY-MM-DD 或空\"}。url 必须来自搜索结果。",
                SEARCH_SCHEMA, web_search=True)
            data = coerce(res.data, SEARCH_SCHEMA)
            validate(data, SEARCH_SCHEMA)
            row["search"] = f"✓ {time.time() - started:.1f}s，引用 {len(res.citations)} 条，示例 {data.get('url', '')[:60]}"
        except (ProviderError, Exception) as e:
            row["search"] = f"✗ {type(e).__name__}: {str(e)[:120]}"
    elif do_search:
        row["search"] = "— 不支持联网"
    return row


def run(settings, router, only: str | None = None, do_search: bool = False) -> tuple[list[dict], list[tuple[str, str, str]]]:
    providers = settings.models.get("providers", {})
    rows = [check_provider(name, cfg, do_search) for name, cfg in providers.items()
            if cfg.get("kind") != "mock" and (only is None or name == only)]
    return rows, router.describe()
