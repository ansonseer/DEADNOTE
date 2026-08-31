"""环境配置。来源见 .env.example；A 线三个变量沿用，B 线新增两个推送凭据。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    corp_id: str
    token: str
    aes_key: str
    corp_secret: str
    agent_id: str
    db_path: str = "data/bot.db"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            corp_id=os.environ["WECOM_CORP_ID"],
            token=os.environ["WECOM_TOKEN"],
            aes_key=os.environ["WECOM_AES_KEY"],
            corp_secret=os.environ["WECOM_CORP_SECRET"],
            agent_id=os.environ["WECOM_AGENT_ID"],
            db_path=os.environ.get("BOT_DB_PATH", "data/bot.db"),
        )
