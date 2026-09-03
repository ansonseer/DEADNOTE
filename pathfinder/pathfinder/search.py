"""网页搜索抽象：验证 JD、团队信息、公开新闻。

四种模式：
- none      ：不搜索，各阶段改为导出 packet（把查询列表和 schema 交给带搜索的人/Agent）。
- tavily / serper / bocha ：通用搜索 API（bocha 是国内的，中文结果更好）。
- claude_web：不走这里，而是在 team_research 时让 Claude 自己用 web_search 工具边搜边写。
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


def get_searcher() -> Searcher:
    provider = (os.environ.get("PF_SEARCH_PROVIDER") or "none").lower()
    if provider == "tavily" and os.environ.get("TAVILY_API_KEY"):
        return TavilySearcher(os.environ["TAVILY_API_KEY"])
    if provider == "serper" and os.environ.get("SERPER_API_KEY"):
        return SerperSearcher(os.environ["SERPER_API_KEY"])
    if provider == "bocha" and os.environ.get("BOCHA_API_KEY"):
        return BochaSearcher(os.environ["BOCHA_API_KEY"])
    return NoneSearcher()


def use_claude_web() -> bool:
    return (os.environ.get("PF_SEARCH_PROVIDER") or "").lower() == "claude_web"
