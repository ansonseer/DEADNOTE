"""Markdown 渲染的小工具：模板用 {{key}} 占位，避免和正文里的花括号打架。"""
from __future__ import annotations

import re
from pathlib import Path

from .config import TEMPLATES_DIR


def load_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def fill(template: str, mapping: dict) -> str:
    def repl(m):
        key = m.group(1).strip()
        val = mapping.get(key, "")
        return "" if val is None else str(val)
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", repl, template)


def bullets(items, empty: str = "（暂无）") -> str:
    items = [str(i) for i in (items or []) if i]
    return "\n".join(f"- {i}" for i in items) if items else f"- {empty}"


def table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "（暂无）"
    head = "| " + " | ".join(headers) + " |\n|" + "---|" * len(headers)
    body = "\n".join("| " + " | ".join(str(c) if c is not None else "" for c in r) + " |" for r in rows)
    return head + "\n" + body


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
