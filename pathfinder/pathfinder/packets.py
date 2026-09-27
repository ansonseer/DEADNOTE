"""Packet：把一个模型任务打包成「prompt + schema + 输入材料」的 Markdown，交给任何带搜索的人或 Agent 去做，
再把 JSON 结果 ingest 回数据库。

这是没有 API key、或者想用 Claude Code / Kimi 网页版亲手研究时的工作方式，
也是"研究不能没有证据来源"这条原则的兜底实现。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import data_dir
from .schemas import BY_TASK, coerce, validate


def _slug(text: str) -> str:
    return re.sub(r"[^\w一-鿿-]+", "_", text).strip("_")[:60]


def export_packet(task: str, context: dict, system: str, user: str, label: str) -> Path:
    out_dir = data_dir() / "packets"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{task}__{_slug(label)}"
    md_path = out_dir / f"{name}.md"
    json_path = out_dir / f"{name}.result.json"
    schema = BY_TASK[task]
    skeleton = {"task": task, "context": context, "result": {}}
    md = f"""# Packet：{task} — {label}

## 怎么用
1. 把下面【System】和【User】两段完整粘贴给一个**能联网搜索**的模型（Kimi 网页版 / Claude Code / 豆包 等）。
2. 让它只输出一个符合【JSON Schema】的 JSON 对象。
3. 把 JSON 填进 `{json_path.name}` 的 `result` 字段（文件已生成骨架），然后运行：
   `pf packet ingest {json_path}`

## System
```
{system}
```

## User
```
{user}
```

## JSON Schema
```json
{json.dumps(schema, ensure_ascii=False, indent=1)}
```
"""
    md_path.write_text(md, encoding="utf-8")
    if not json_path.exists():
        json_path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=1), encoding="utf-8")
    return md_path


def load_packet_result(path: Path) -> tuple[str, dict, dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    task, context, result = payload.get("task"), payload.get("context", {}), payload.get("result")
    if task not in BY_TASK:
        raise ValueError(f"未知任务：{task}")
    if not result:
        raise ValueError("result 为空：请先把模型输出填进 result 字段")
    result = coerce(result, BY_TASK[task])
    validate(result, BY_TASK[task])
    return task, context, result


def ingest(conn, settings, path: Path) -> str:
    """按任务分发到对应阶段的 ingest 函数。"""
    from .stages import scan, discover, research, people, rank

    task, context, result = load_packet_result(path)
    handlers = {
        "company_enrich": scan.ingest_enrich,
        "title_expand": discover.ingest_titles,
        "jd_classify": discover.ingest_classify,
        "team_research": research.ingest_research,
        "people_assess": people.ingest_assess,
        "fit_assess": rank.ingest_fit,
    }
    if task not in handlers:
        raise ValueError(f"任务 {task} 不支持 packet 导入（outreach / card 请直接用 CLI 生成）")
    return handlers[task](conn, settings, context, result)
