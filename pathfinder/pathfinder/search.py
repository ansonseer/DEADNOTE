"""网页搜索抽象：验证 JD、团队信息、公开新闻。

几种模式（PF_SEARCH_PROVIDER）：
- native    ：不走这里；研究模型用自己的联网工具（Kimi $web_search / 智谱 web_search / Claude web_search）边搜边写。
- zhipu     ：智谱独立的 Web Search API（专为大模型设计的搜索，中文友好），结果喂给任意模型。
- bocha / tavily / serper ：其他搜索 API（bocha 也是国内的）。
- none      ：不搜索，各阶段改为导出 packet（把查询列表和 schema 交给带搜索的人/Agent）。
统一返回 SearchResult，方便替换。
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, asdict


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    date: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Searcher:
    name = "none"

    def search(self, query: str, n: int = 8) -> list[SearchResult]:
        return []

    @property
    def enabled(self) -> bool:
        return False


class NoneSearcher(Searcher):
    pass


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class TavilySearcher(Searcher):
    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    enabled = True

    def search(self, query: str, n: int = 8) -> list[SearchResult]:
        data = _post_json(
            "https://api.tavily.com/search",
            {"api_key": self.api_key, "query": query, "max_results": n, "search_depth": "basic"},
            {},
        )
        return [SearchResult(r.get("title", ""), r.get("url", ""), r.get("content", ""), r.get("published_date", "") or "")
                for r in data.get("results", [])]


class SerperSearcher(Searcher):
    name = "serper"

    def __init__(self, api_key: str):
        self.api_key = api_key

    enabled = True

    def search(self, query: str, n: int = 8) -> list[SearchResult]:
        data = _post_json(
            "https://google.serper.dev/search",
            {"q": query, "num": n, "gl": "cn", "hl": "zh-cn"},
            {"X-API-KEY": self.api_key},
        )
        return [SearchResult(r.get("title", ""), r.get("link", ""), r.get("snippet", ""), r.get("date", "") or "")
                for r in data.get("organic", [])]


class BochaSearcher(Searcher):
    name = "bocha"

    def __init__(self, api_key: str):
        self.api_key = api_key

    enabled = True

    def search(self, query: str, n: int = 8) -> list[SearchResult]:
        data = _post_json(
            "https://api.bochaai.com/v1/web-search",
            {"query": query, "count": n, "summary": True},
            {"Authorization": f"Bearer {self.api_key}"},
        )
        pages = (data.get("data") or {}).get("webPages", {}).get("value", [])
        return [SearchResult(r.get("name", ""), r.get("url", ""), r.get("summary") or r.get("snippet", ""), r.get("datePublished", "") or "")
                for r in pages]


class ZhipuSearcher(Searcher):
    """智谱 Web Search API：POST /api/paas/v4/web_search → search_result[{title, link, content, publish_date, ...}]"""
    name = "zhipu"

    def __init__(self, api_key: str, engine: str = "search_std"):
        self.api_key = api_key
        self.engine = engine

    enabled = True

    def search(self, query: str, n: int = 8) -> list[SearchResult]:
        data = _post_json(
            "https://open.bigmodel.cn/api/paas/v4/web_search",
            {"search_engine": self.engine, "search_query": query, "count": max(1, min(n, 50))},
            {"Authorization": f"Bearer {self.api_key}"},
        )
        return [SearchResult(r.get("title", ""), r.get("link", ""), r.get("content", ""), r.get("publish_date", "") or "")
                for r in data.get("search_result", []) or []]


def get_searcher() -> Searcher:
    provider = (os.environ.get("PF_SEARCH_PROVIDER") or "none").lower()
    if provider == "tavily" and os.environ.get("TAVILY_API_KEY"):
        return TavilySearcher(os.environ["TAVILY_API_KEY"])
    if provider == "serper" and os.environ.get("SERPER_API_KEY"):
        return SerperSearcher(os.environ["SERPER_API_KEY"])
    if provider == "bocha" and os.environ.get("BOCHA_API_KEY"):
        return BochaSearcher(os.environ["BOCHA_API_KEY"])
    if provider == "zhipu" and os.environ.get("ZHIPU_API_KEY"):
        return ZhipuSearcher(os.environ["ZHIPU_API_KEY"], os.environ.get("ZHIPU_SEARCH_ENGINE", "search_std"))
    return NoneSearcher()


def use_native_search() -> bool:
    """PF_SEARCH_PROVIDER=native（或旧写法 claude_web）：让研究模型自己联网。"""
    return (os.environ.get("PF_SEARCH_PROVIDER") or "").lower() in ("native", "claude_web")
