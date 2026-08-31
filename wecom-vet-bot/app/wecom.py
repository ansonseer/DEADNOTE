"""企业微信服务端 API 客户端：access_token 内存缓存 + message/send 主动推送。

token 约 7200s 有效；提前 REFRESH_MARGIN 秒主动换新，避免拿着将过期的 token
去撞 42001。真撞上（服务端提前作废等）则强刷一次并重试该条发送。
"""

import asyncio
import time

import httpx

GETTOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

REFRESH_MARGIN = 300  # 秒
# 40014 invalid access_token / 42001 access_token 已过期
_STALE_TOKEN_CODES = (40014, 42001)


class WeComApiError(RuntimeError):
    pass


class WeComClient:
    def __init__(self, corp_id: str, corp_secret: str, agent_id: str, http=None):
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = int(agent_id)
        self._http = http or httpx.AsyncClient(timeout=10)
        self._token = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_access_token(self, force: bool = False) -> str:
        async with self._lock:
            now = time.monotonic()
            if not force and self._token and now < self._expires_at - REFRESH_MARGIN:
                return self._token
            resp = await self._http.get(
                GETTOKEN_URL,
                params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                raise WeComApiError(f"gettoken failed: {data}")
            self._token = data["access_token"]
            self._expires_at = now + data.get("expires_in", 7200)
            return self._token

    async def send_text(self, touser: str, content: str) -> dict:
        for attempt in (1, 2):
            token = await self.get_access_token(force=attempt == 2)
            resp = await self._http.post(
                SEND_URL,
                params={"access_token": token},
                json={
                    "touser": touser,
                    "msgtype": "text",
                    "agentid": self.agent_id,
                    "text": {"content": content},
                    "safe": 0,
                },
            )
            data = resp.json()
            code = data.get("errcode", 0)
            if code == 0:
                return data
            if code in _STALE_TOKEN_CODES and attempt == 1:
                continue
            raise WeComApiError(f"message/send failed: {data}")

    async def aclose(self) -> None:
        await self._http.aclose()
