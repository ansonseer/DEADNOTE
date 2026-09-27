"""模型输出的 JSON Schema + 一个够用的轻量校验器。

为什么每个模型任务都要有 schema：
1. 模型的输出必须能被代码消费（打分、入库），不能是一段自由文本；
2. 出错时能定位到字段，而不是整段重来；
3. schema 本身就是给模型的"输出说明书"，会原样放进 prompt。
"""
from __future__ import annotations

from typing import Any

DIRECTIONS = ["agent", "enterprise_ai", "industry_delivery", "platform", "model_research", "consumer", "unknown"]
ROLE_TYPES = ["hiring_manager", "team_lead", "senior_ic", "exec", "employee", "recruiter"]
SIGNAL_KINDS = ["news", "product", "hiring", "talk", "org", "open_source"]
LONG_TERM_TAGS = ["hiring_now", "future_client_au", "au_cn_bridge", "collaborator", "distribution", "mentor", "peer", "alumni"]
CHANNELS = ["maimai", "linkedin", "wechat", "email", "zhihu", "jike", "github", "other"]


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required if required is not None else list(props),
        "additionalProperties": False,
    }


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}


def _score(lo: int = 0, hi: int = 10) -> dict:
    return {"type": "integer", "minimum": lo, "maximum": hi}


TITLE_EXPAND = _obj({
    "category_id": I,
    "titles": _arr(S),
    "search_queries": _arr(S),
    "notes": S,
})

COMPANY_ENRICH = _obj({
    "teams": _arr(_obj({
        "name": S,
        "bu": S,
        "direction": {"type": "string", "enum": DIRECTIONS},
        "description": S,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "how_to_verify": S,
    })),
    "hiring_style": S,
    "culture_notes": S,
    "watchouts": S,
})

JD_CLASSIFY = _obj({
    "category_id": _score(0, 3),
    "role_match": _score(),
    "seniority_fit": _score(),
    "direction": {"type": "string", "enum": DIRECTIONS},
    "years_required": S,
    "city": S,
    "negative_hits": _arr(S),
    "key_responsibilities": _arr(S),
    "key_requirements": _arr(S),
    "summary": S,
})

TEAM_RESEARCH = _obj({
    "team_name": S,
    "direction": {"type": "string", "enum": DIRECTIONS},
    "what_they_do_now": S,
    "signals": _arr(_obj({
        "kind": {"type": "string", "enum": SIGNAL_KINDS},
        "title": S,
        "url": S,
        "date": S,
        "summary": S,
        "strength": _score(1, 3),
    })),
    "why_they_need_this_role": S,
    "conversation_hooks": _arr(S),
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
})

PEOPLE_ASSESS = _obj({
    "people": _arr(_obj({
        "name": S,
        "role_type": {"type": "string", "enum": ROLE_TYPES},
        "why_contact": S,
        "hook": S,
        "suggested_channel": {"type": "string", "enum": CHANNELS},
        "path_level_potential": _score(1, 5),
        "long_term_tags": _arr({"type": "string", "enum": LONG_TERM_TAGS}),
        "risk": S,
    })),
    "recommended_first": S,
    "rationale": S,
})

FIT_ASSESS = _obj({
    "experience_overlap": _score(),
    "matched_points": _arr(_obj({"jd_need": S, "your_evidence": S})),
    "gaps": _arr(S),
    "why_fit_summary": S,
})

OUTREACH_WRITE = _obj({
    "channel": {"type": "string", "enum": CHANNELS},
    "first_message": S,
    "followup_1": S,
    "followup_2": S,
    "referral_transition": S,
    "email_subject": S,
    "notes": S,
})

CARD_WRITE = _obj({
    "why_fit": S,
    "team_now": S,
    "why_this_person": S,
    "referral_assessment": S,
    "next_action": S,
    "risks": S,
})

BY_TASK: dict[str, dict] = {
    "title_expand": TITLE_EXPAND,
    "company_enrich": COMPANY_ENRICH,
    "jd_classify": JD_CLASSIFY,
    "team_research": TEAM_RESEARCH,
    "people_assess": PEOPLE_ASSESS,
    "fit_assess": FIT_ASSESS,
    "outreach_write": OUTREACH_WRITE,
    "card_write": CARD_WRITE,
}


class SchemaError(ValueError):
    pass


def validate(obj: Any, schema: dict, path: str = "$") -> None:
    """支持 type / properties / required / additionalProperties / items / enum / minimum / maximum。够用即可。"""
    t = schema.get("type")
    if t == "object":
        if not isinstance(obj, dict):
            raise SchemaError(f"{path}: 应为 object，实际 {type(obj).__name__}")
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in obj:
                raise SchemaError(f"{path}.{key}: 缺少必填字段")
        if schema.get("additionalProperties") is False:
            extra = set(obj) - set(props)
            if extra:
                raise SchemaError(f"{path}: 多余字段 {sorted(extra)}")
        for key, sub in props.items():
            if key in obj:
                validate(obj[key], sub, f"{path}.{key}")
    elif t == "array":
        if not isinstance(obj, list):
            raise SchemaError(f"{path}: 应为 array，实际 {type(obj).__name__}")
        for i, item in enumerate(obj):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    elif t == "string":
        if not isinstance(obj, str):
            raise SchemaError(f"{path}: 应为 string，实际 {type(obj).__name__}")
        if "enum" in schema and obj not in schema["enum"]:
            raise SchemaError(f"{path}: 值 {obj!r} 不在 {schema['enum']}")
    elif t == "integer":
        if isinstance(obj, bool) or not isinstance(obj, int):
            if isinstance(obj, float) and obj.is_integer():
                obj = int(obj)
            else:
                raise SchemaError(f"{path}: 应为 integer，实际 {obj!r}")
        _range(obj, schema, path)
    elif t == "number":
        if isinstance(obj, bool) or not isinstance(obj, (int, float)):
            raise SchemaError(f"{path}: 应为 number，实际 {obj!r}")
        _range(obj, schema, path)
    elif t == "boolean":
        if not isinstance(obj, bool):
            raise SchemaError(f"{path}: 应为 boolean，实际 {obj!r}")


def _range(value: float, schema: dict, path: str) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        raise SchemaError(f"{path}: {value} 小于最小值 {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise SchemaError(f"{path}: {value} 大于最大值 {schema['maximum']}")


def coerce(obj: Any, schema: dict) -> Any:
    """温和修正：整数字段收到 7.0 → 7；分数越界 → 夹到边界。校验前调用，减少无意义的重试。"""
    t = schema.get("type")
    if t == "object" and isinstance(obj, dict):
        return {k: coerce(v, schema.get("properties", {}).get(k, {})) for k, v in obj.items()}
    if t == "array" and isinstance(obj, list):
        return [coerce(v, schema.get("items", {})) for v in obj]
    if t == "integer" and isinstance(obj, float) and obj.is_integer():
        obj = int(obj)
    if t in {"integer", "number"} and isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema:
            obj = max(schema["minimum"], obj)
        if "maximum" in schema:
            obj = min(schema["maximum"], obj)
    return obj
