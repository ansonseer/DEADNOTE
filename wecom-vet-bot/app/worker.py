"""异步 worker：消费队列 → 处理 → message/send 主动推送 → 落日志。

单 worker 顺序消费（诊所量级足够）；任何一条消息的异常只标记该条为
failed，绝不让 worker 循环退出——渠道层还在继续确认新消息。
"""

import asyncio
import logging
import time

from . import db

logger = logging.getLogger("wecom-vet-bot.worker")


async def run_worker(queue: asyncio.Queue, db_path: str, wecom_client, handler) -> None:
    while True:
        msg = await queue.get()
        started = time.monotonic()
        try:
            reply = await handler(msg)
            await wecom_client.send_text(msg["from_user"], reply)
            latency_ms = int((time.monotonic() - started) * 1000)
            db.mark_done(db_path, msg["msg_key"], reply, latency_ms)
            logger.info("done msg_key=%s latency_ms=%d", msg["msg_key"], latency_ms)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            db.mark_failed(db_path, msg["msg_key"], repr(exc), latency_ms)
            logger.exception("failed msg_key=%s", msg["msg_key"])
        finally:
            queue.task_done()
