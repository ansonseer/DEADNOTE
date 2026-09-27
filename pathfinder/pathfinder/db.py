"""SQLite 数据层：系统的"记账本"。

表的设计对应 workflow 的每一步：
companies → teams → jobs / signals → people → opportunities → touchpoints / tasks
外加 assets（你的公开作品，social proof）、runs（每次模型调用的成本记录）、queries（搜过什么）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

from .config import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  aliases TEXT, tier INTEGER, hq TEXT,
  au_footprint INTEGER DEFAULT 0,
  why TEXT, careers_url TEXT,
  status TEXT DEFAULT 'seed',          -- seed | enriched | pilot | bench | excluded
  screen_score REAL DEFAULT 0,
  screen_boost REAL DEFAULT 0,               -- seeds.yaml 里的人工加减分
  enrich TEXT,                         -- JSON：company_enrich 的输出
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  name TEXT NOT NULL, bu TEXT,
  direction TEXT DEFAULT 'unknown',    -- agent | enterprise_ai | industry_delivery | platform | model_research | consumer | unknown
  description TEXT,
  confidence REAL DEFAULT 0.3,
  verified INTEGER DEFAULT 0,          -- 0 假设  1 有公开来源证实
  research TEXT,                       -- JSON：team_research 的输出
  created_at TEXT, updated_at TEXT,
  UNIQUE(company_id, name)
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  team_id INTEGER REFERENCES teams(id),
  title TEXT NOT NULL,
  category_id INTEGER DEFAULT 0,       -- 0 不相关 / 未分类；1 售前解决方案；2 AI 应用；3 校招管培
  url TEXT, city TEXT, seniority TEXT,
  jd_text TEXT, source TEXT, posted_at TEXT,
  verified INTEGER DEFAULT 0,          -- 1 = 在官方来源看到过完整 JD
  status TEXT DEFAULT 'candidate',     -- candidate | classified | rejected
  features TEXT,                       -- JSON：jd_classify 的输出
  fit TEXT,                            -- JSON：fit_assess 的输出
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  team_id INTEGER REFERENCES teams(id),
  kind TEXT,                           -- news | product | hiring | talk | org | open_source
  title TEXT, url TEXT, date TEXT, summary TEXT,
  strength INTEGER DEFAULT 1,          -- 1 弱 2 中 3 强
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  team_id INTEGER REFERENCES teams(id),
  name TEXT NOT NULL, title TEXT,
  role_type TEXT DEFAULT 'employee',   -- hiring_manager | team_lead | senior_ic | exec | employee | recruiter
  channels TEXT,                       -- JSON：{"linkedin": url, "maimai": ..., "wechat": "", "email": ""}
  evidence TEXT,                       -- JSON：[{"title","url","summary"}] 公开分享/文章/演讲
  why_contact TEXT, hook TEXT,
  path_level INTEGER DEFAULT 1,        -- 0-5，见 scoring.yaml
  relationship TEXT DEFAULT 'cold',    -- cold | contacted | replied | warm | advocate | parked
  tags TEXT, horizon TEXT,             -- JSON 数组：长期人脉标签 / 时间维度
  notes TEXT,
  value_given INTEGER DEFAULT 0, asks INTEGER DEFAULT 0,
  assess TEXT,                         -- JSON：people_assess 的输出
  last_touch_at TEXT, next_action_at TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS opportunities (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  team_id INTEGER REFERENCES teams(id),
  job_id INTEGER REFERENCES jobs(id),
  person_id INTEGER REFERENCES people(id),
  fit_score REAL DEFAULT 0, tier TEXT DEFAULT 'C',
  breakdown TEXT,                      -- JSON：各维度得分与证据
  stage TEXT DEFAULT 'identified',
  next_action TEXT, next_action_at TEXT,
  narrative TEXT,                      -- JSON：card_write 的输出
  outreach TEXT,                       -- JSON：outreach_write 的输出
  card_path TEXT,
  created_at TEXT, updated_at TEXT,
  UNIQUE(company_id, team_id, job_id)
);
CREATE TABLE IF NOT EXISTS touchpoints (
  id INTEGER PRIMARY KEY,
  opportunity_id INTEGER REFERENCES opportunities(id),
  person_id INTEGER REFERENCES people(id),
  channel TEXT, direction TEXT,        -- out | in
  kind TEXT,                           -- first_msg | followup | reply | call | meeting | referral | value_given | note
  content TEXT, outcome TEXT,
  at TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY,
  opportunity_id INTEGER REFERENCES opportunities(id),
  person_id INTEGER REFERENCES people(id),
  action TEXT NOT NULL,
  due_at TEXT, done_at TEXT,
  priority TEXT DEFAULT 'B',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY,
  kind TEXT,                           -- poc | post | teardown | talk | repo | case_study
  title TEXT, url TEXT,
  status TEXT DEFAULT 'idea',          -- idea | draft | published
  company_id INTEGER, person_id INTEGER,
  notes TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  task TEXT, provider TEXT, model TEXT,
  input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
  seconds REAL DEFAULT 0, ok INTEGER DEFAULT 1, error TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY,
  stage TEXT, company_id INTEGER, query TEXT, provider TEXT,
  n_results INTEGER DEFAULT 0, created_at TEXT
);
"""

# 机会的阶段（状态机）。顺序即漏斗顺序。
STAGES = [
    "identified", "researched", "people_found", "outreach_drafted", "contacted",
    "replied", "in_conversation", "referral_requested", "referred", "applied",
    "interviewing", "offer", "closed_won", "closed_lost", "parked",
]
TERMINAL_STAGES = {"closed_won", "closed_lost", "parked"}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes")


def hours_from_now(hours: float) -> str:
    return (datetime.now(timezone.utc).astimezone() + timedelta(hours=hours)).isoformat(timespec="minutes")


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def j(obj: Any) -> str | None:
    return None if obj is None else json.dumps(obj, ensure_ascii=False)


def unj(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def db_path() -> Path:
    return data_dir() / "pathfinder.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# 后加的列写在这里：老数据库打开时自动补列，不用删库重来。
MIGRATIONS = [("companies", "screen_boost", "REAL DEFAULT 0")]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def rows(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def one(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> dict | None:
    r = conn.execute(sql, tuple(params)).fetchone()
    return dict(r) if r else None


def insert(conn: sqlite3.Connection, table: str, row: dict) -> int:
    row = {k: v for k, v in row.items() if v is not None}
    row.setdefault("created_at", now())
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    conn.commit()
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, table: str, row_id: int, fields: dict) -> None:
    if not fields:
        return
    if table in {"companies", "teams", "jobs", "people", "opportunities"}:
        fields = {**fields, "updated_at": now()}
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*fields.values(), row_id))
    conn.commit()


def get(conn: sqlite3.Connection, table: str, row_id: int) -> dict | None:
    return one(conn, f"SELECT * FROM {table} WHERE id = ?", (row_id,))


# ---- 常用查找 ----

def find_company(conn: sqlite3.Connection, ref: str | int) -> dict | None:
    """按 id、名字或别名找公司。"""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return get(conn, "companies", int(ref))
    row = one(conn, "SELECT * FROM companies WHERE name = ?", (ref,))
    if row:
        return row
    for c in rows(conn, "SELECT * FROM companies"):
        aliases = unj(c.get("aliases"), []) or []
        if ref in aliases or ref in c["name"] or c["name"] in ref:
            return c
    return None


def upsert_company(conn: sqlite3.Connection, name: str, **fields) -> int:
    existing = one(conn, "SELECT id FROM companies WHERE name = ?", (name,))
    if existing:
        update(conn, "companies", existing["id"], fields)
        return existing["id"]
    return insert(conn, "companies", {"name": name, **fields})


def upsert_team(conn: sqlite3.Connection, company_id: int, name: str, **fields) -> int:
    existing = one(conn, "SELECT id FROM teams WHERE company_id = ? AND name = ?", (company_id, name))
    if existing:
        update(conn, "teams", existing["id"], fields)
        return existing["id"]
    return insert(conn, "teams", {"company_id": company_id, "name": name, **fields})


def pilot_companies(conn: sqlite3.Connection) -> list[dict]:
    return rows(conn, "SELECT * FROM companies WHERE status = 'pilot' ORDER BY screen_score DESC, tier ASC")


def log_run(conn: sqlite3.Connection | None, **fields) -> None:
    if conn is None:
        return
    insert(conn, "runs", fields)
