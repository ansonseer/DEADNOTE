"""渠道层：企业微信回调入口。

B 线核心改动——被动回复换成「立即确认 + 异步主动推送」：
POST 只做 验签解密 → MsgId 幂等检查 → 入队，然后返回空串（企业微信收到
空响应即认为送达成功，不再重试，也不展示被动回复）。真正的处理与推送
全部在 worker 里异步完成，5 秒窗口从此与处理耗时无关。
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from wechatpy.enterprise import parse_message
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.exceptions import InvalidSignatureException

from . import db
from .config import Settings
from .handler import echo_handler
from .wecom import WeComClient
from .worker import run_worker

logger = logging.getLogger("wecom-vet-bot.server")


def create_app(settings: Settings, wecom_client=None, handler=None) -> FastAPI:
    """wecom_client / handler 可注入替身，测试不出网；缺省用真实实现。"""
    crypto = WeChatCrypto(settings.token, settings.aes_key, settings.corp_id)
    handler = handler or echo_handler
    owns_client = wecom_client is None
    if owns_client:
        wecom_client = WeComClient(
            settings.corp_id, settings.corp_secret, settings.agent_id
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db(settings.db_path)
        queue: asyncio.Queue = asyncio.Queue()
        # 重启恢复：确认过但没处理完的消息重新入队，不静默丢
        for row in db.fetch_unfinished(settings.db_path):
            queue.put_nowait(
                {
                    "msg_key": row["msg_id"],
                    "from_user": row["from_user"],
                    "msg_type": row["msg_type"],
                    "content": row["content"],
                }
            )
        worker_task = asyncio.create_task(
            run_worker(queue, settings.db_path, wecom_client, handler)
        )
        app.state.queue = queue
        yield
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task
        if owns_client:
            await wecom_client.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/wecom/callback")
    async def verify_url(msg_signature: str, timestamp: str, nonce: str, echostr: str):
        """企业微信保存回调配置时的 URL 验证：解密后的 echostr 裸文本原样返回。"""
        try:
            echo = crypto.check_signature(msg_signature, timestamp, nonce, echostr)
        except InvalidSignatureException:
            return PlainTextResponse("signature check failed", status_code=403)
        return PlainTextResponse(echo)

    @app.post("/wecom/callback")
    async def receive_message(
        request: Request, msg_signature: str, timestamp: str, nonce: str
    ):
        body = await request.body()
        try:
            xml = crypto.decrypt_message(body, msg_signature, timestamp, nonce)
        except InvalidSignatureException:
            return PlainTextResponse("signature check failed", status_code=403)

        msg = parse_message(xml)
        create_time = int(getattr(msg, "time", 0) or 0)
        # 事件消息没有 MsgId（wechatpy 里为 0），用 来源+时间+类型 合成幂等键
        msg_key = (
            str(msg.id)
            if getattr(msg, "id", None)
            else f"{msg.source}:{create_time}:{msg.type}"
        )
        content = getattr(msg, "content", None)

        is_new = db.insert_message_if_new(
            settings.db_path, msg_key, msg.source, msg.type, content, create_time
        )
        if not is_new:
            logger.info("duplicate msg_key=%s（企业微信重试），跳过", msg_key)
        elif msg.type == "event":
            # 进入应用等事件只记账不回复
            db.mark_skipped(
                settings.db_path, msg_key, f"event:{getattr(msg, 'event', 'unknown')}"
            )
        else:
            request.app.state.queue.put_nowait(
                {
                    "msg_key": msg_key,
                    "from_user": msg.source,
                    "msg_type": msg.type,
                    "content": content,
                }
            )
        return PlainTextResponse("")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
