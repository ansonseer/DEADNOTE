"""消息处理逻辑（工作层的可替换核心）。

B 线：回声，行为与 A 线被动回复一致。
C 线：这里换成 检索 → 前置围栏 → 生成 → grounding 校验 的 RAG 管道。

约定：入参是渠道无关的纯 dict（msg_key/from_user/msg_type/content），
返回要推送给用户的文本——渠道层可替换的边界就划在这里。
"""


async def echo_handler(msg: dict) -> str:
    if msg["msg_type"] == "text":
        return f"收到：{msg['content']}"
    return "我现在只会复读文字消息～"
