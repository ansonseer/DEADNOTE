"""配置加载：config/*.yaml + .env。

所有可调的东西（评分权重、岗位词典、模型分工、种子公司）都在 YAML 里，
改配置不改代码，是让这个系统能被你自己持续迭代的关键。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("PF_ROOT") or Path(__file__).resolve().parent.parent)
CONFIG_DIR = ROOT / "config"
TEMPLATES_DIR = ROOT / "templates"


def data_dir() -> Path:
    """运行时数据目录（数据库、作战卡、packet、日报）。测试时用 PF_DATA_DIR 指到临时目录。"""
    d = Path(os.environ.get("PF_DATA_DIR") or ROOT / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_env(path: Path | None = None) -> None:
    """极简 .env 读取：不覆盖已存在的环境变量。"""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    p = CONFIG_DIR / f"{name}.yaml"
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Settings:
    """把六份配置聚在一起，方便各阶段传递。"""

    @property
    def profile(self) -> dict:
        return load_yaml("profile")

    @property
    def scoring(self) -> dict:
        return load_yaml("scoring")

    @property
    def taxonomy(self) -> dict:
        return load_yaml("taxonomy")

    @property
    def seeds(self) -> dict:
        return load_yaml("seeds")

    @property
    def sources(self) -> dict:
        return load_yaml("sources")

    @property
    def models(self) -> dict:
        return load_yaml("models")

    def category_name(self, category_id: int) -> str:
        for c in self.taxonomy.get("categories", []):
            if c["id"] == category_id:
                return c["name"]
        return "不相关"

    def category_priority(self, category_id: int) -> float:
        for c in self.profile.get("target_categories", []):
            if c["id"] == category_id:
                return float(c.get("priority", 1.0))
        return 0.0


settings = Settings()
