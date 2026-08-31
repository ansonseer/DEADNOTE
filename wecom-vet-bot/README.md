# 兽医 Bot · 企业微信版

兽医诊所 AI 客服的企业微信管道。A 线（回调验证 + 加密收发 + 被动回复回声）见
[ansonseer/Wechat-Bot-](https://github.com/ansonseer/Wechat-Bot-/blob/main/echo_bot.py)，
本目录从 B 线开始：**立即确认 + 异步处理 + MsgId 幂等 + 全链路日志**。

## 当前进度

- [x] B 线｜异步骨架：幂等检查 → 入队 → 返回 ""；worker 回声 + message/send 主动推送；messages 表全量日志
- [ ] C 线｜RAG MVP（sqlite-vec + bge 本地 embedding）
- [ ] D 线｜护栏（前置围栏 + 后置 grounding）
- [ ] E 线｜评测门禁（golden set 三指标）
- [ ] F 线｜生产化（回国后）

## 架构（B 线落地部分）

```
企业微信客户端
   │ 加密XML POST
   ▼
[渠道层] FastAPI /wecom/callback          app/server.py
   ├─ 验签解密（A线复用）
   ├─ MsgId 幂等检查 ──重复──▶ 直接返回 ""
   ├─ 入队（asyncio.Queue）
   └─ 立即返回 ""（5秒内确认，不做被动回复）
   ▼
[工作层] 异步 worker                       app/worker.py
   ├─ 处理：B线为回声逻辑                  app/handler.py（C线换成 RAG 管道）
   └─ 主动推送：message/send API           app/wecom.py（access_token 缓存~7200s）
   ▼
[存储] SQLite 单文件                       app/db.py
   └─ messages（msg_id 唯一键；reply/latency/status 已落，
       retrieval/prompt/guardrail/token 字段为 C/D 线预留——可回放）
```

## 运行

```bash
pip install -r requirements.txt

export WECOM_CORP_ID=...        # 见 .env.example 各项来源
export WECOM_TOKEN=...
export WECOM_AES_KEY=...
export WECOM_CORP_SECRET=...    # B线新增
export WECOM_AGENT_ID=...       # B线新增

uvicorn main:app --host 0.0.0.0 --port 8000
ngrok http 8000    # 回调URL填 https://xxx.ngrok.io/wecom/callback
```

## 验收测试

```bash
python -m pytest tests -v
```

对应交接简报 B 线验收：

| 验收项 | 测试 |
|---|---|
| 同一条消息模拟重试 3 次只回 1 次 | `test_same_message_retried_3_times_pushes_once` |
| 处理耗时 >5 秒的消息正常送达（回调 <1s 确认） | `test_slow_processing_acks_immediately_and_still_delivers` |
| messages 表落全量日志 | `test_messages_table_logs_full_pipeline` |
| access_token 缓存 / 过期刷新 / 42001 强刷重试 | `test_access_token_*` |
| A 线回归：GET 验证 / 坏签名 403 / health | `test_url_verification_*`、`test_invalid_signature_*`、`test_health` |

## 人工步骤（代码之外，B 线验收前提）

1. **企业可信 IP**：`message/send` 是服务器**出站**调用，企业微信校验调用方出口 IP。
   管理后台 → 应用管理 → 该应用 → 「企业可信IP」，填服务器出口 IP（`curl ifconfig.me` 查看）。
   注意是服务器出口 IP，不是 ngrok 域名的 IP；家用宽带 IP 变化后要更新。
2. 应用 Secret 与 AgentId 写入环境变量（见 `.env.example`）。

## 设计约束（交接简报 §4，已定死）

无编排框架；SQLite `messages.msg_id UNIQUE` 做幂等（插入冲突即跳过）；
access_token 内存缓存、过期前刷新；渠道层可替换（worker 只消费纯 dict，
不感知企业微信 XML）。
