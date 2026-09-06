# -*- coding: utf-8 -*-
"""飞书 WebSocket 长连接客户端。

后端启动时主动连飞书 WebSocket，接收消息事件，**不需要公网回调 URL**。
这是 OpenClaw 调研报告（docs/openclaw-chat-integration-survey.md）推荐的模式，
本地开发直接可用（无需 ngrok / 公网域名 / 事件回调配置）。

工作流：
    飞书用户 @机器人发消息
        → 飞书服务端通过 WebSocket 推 P2ImMessageReceiveV1 事件
        → do_p2_im_message_receive_v1 回调（lark-oapi 内部线程）
        → 意图识别（KG 直查） + LLM 兜底
        → lark.Client 通过 IM API 回发消息

合规（CLAUDE.md §1 弱合规）：本模块只做「事件接入 → AI 对话 → 回复」
管道，不预置标的、不建议；方向性研判由 chat 层 SYSTEM_PROMPT 约束。
"""
from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Any, Optional

from config import default_config

if TYPE_CHECKING:
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

logger = logging.getLogger(__name__)

# 全局客户端引用（供 stop / 状态查询；当前 lark.ws.Client 无显式 stop API，
# daemon 线程随进程退出自然终止）
_client: Any = None
_thread: Optional[threading.Thread] = None


def start_feishu_ws() -> None:
    """启动飞书 WebSocket 长连接（非阻塞，daemon 线程）。

    幂等：重复调用只启动一次。缺 SDK 或缺凭据时静默降级（仅 warning log），
    不阻断 app 启动——这是通知/对话增强功能，不是核心数据层。
    """
    global _client, _thread
    if _thread is not None and _thread.is_alive():
        logger.debug("飞书 WebSocket 长连接已在运行，跳过重复启动")
        return

    try:
        import lark_oapi as lark  # noqa: F401  (仅探测可用性)
    except ImportError:
        logger.warning("lark-oapi 未安装，飞书 WebSocket 长连接不可用")
        return

    cfg = default_config
    if not cfg.feishu_app_id or not cfg.feishu_app_secret:
        logger.warning(
            "飞书 app_id/secret 未配置（FEISHU_APP_ID/FEISHU_APP_SECRET），"
            "WebSocket 长连接不可用"
        )
        return

    # 事件分发器：注册 im.message.receive_v1 事件回调
    event_dispatcher = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
        .build()
    )

    # WebSocket 长连接客户端
    cli = lark.ws.Client(
        cfg.feishu_app_id,
        cfg.feishu_app_secret,
        event_handler=event_dispatcher,
        log_level=lark.LogLevel.INFO,
    )
    _client = cli

    def _run() -> None:
        try:
            cli.start()
        except Exception as e:  # noqa: BLE001 — daemon 线程异常不能冒泡到主进程
            logger.error("飞书 WebSocket 长连接异常退出: %s", e)

    _thread = threading.Thread(target=_run, name="feishu-ws", daemon=True)
    _thread.start()
    logger.info(
        "飞书 WebSocket 长连接已启动（app_id=%s…）",
        cfg.feishu_app_id[:12],
    )


def do_p2_im_message_receive_v1(data: "P2ImMessageReceiveV1") -> None:
    """处理接收到的消息事件（lark-oapi 内部线程调用）。

    策略（与 routers.feishu_bot / wechat_bot 一致）：
        1. KG 直查能答 → KG 结果纯文本回发
        2. LLM 可用 → 调 chat.run_chat 兜底回复
        3. 两者都失败 → 帮助提示

    chat.run_chat 是同步阻塞函数（含 LLM HTTP 调用），不能在 lark-oapi
    事件线程直接调（会阻塞事件分发）。丢到独立线程池异步处理，回调立即返回。
    """
    try:
        msg = data.event.message
        chat_id = getattr(msg, "chat_id", "") or ""
        raw_content = getattr(msg, "content", "") or ""
    except Exception as e:  # noqa: BLE001 — 事件结构异常不能冒泡
        logger.error("飞书 WS 事件解析失败: %s", e)
        return

    # 提取文本（飞书 text 消息 content 是 {"text": "..."} JSON）
    text = ""
    try:
        content = json.loads(raw_content)
        text = content.get("text", "")
    except (ValueError, TypeError):
        text = ""

    if not text:
        return

    # 去 @机器人前缀
    text = text.strip()
    if text.startswith("@_user"):
        text = text.split(" ", 1)[-1] if " " in text else ""
    text = text.strip()
    if not text:
        return

    # 异步处理（不阻塞 lark-oapi 事件分发线程）
    t = threading.Thread(
        target=_handle_message,
        args=(text, chat_id),
        name="feishu-ws-handle",
        daemon=True,
    )
    t.start()


def _handle_message(text: str, chat_id: str) -> None:
    """实际处理消息（工作线程内执行）。

    与 routers.feishu_bot.feishu_bot_webhook 保持相同的回复优先级：
    KG 直查 → LLM 兜底 → 帮助提示。
    """
    from routers.feishu_bot import _direct_kg_lookup
    from routers.wechat_bot import _format_kg_as_text

    # 1. KG 直查（轻量，不经 LLM）
    try:
        kg_result = _direct_kg_lookup(text)
    except Exception as e:  # noqa: BLE001 — KG 工具异常降级到 LLM
        logger.warning("飞书 WS KG 直查失败: %s", e)
        kg_result = None

    if kg_result is not None:
        reply_text = _format_kg_as_text(kg_result)
        _send_message(chat_id, reply_text)
        return

    # 2. LLM 兜底（如果配置了 VR_LLM_*）
    reply = None
    try:
        import chat
        cfg = chat._get_env_llm_config()
        if cfg.get("baseURL") and cfg.get("apiKey"):
            result = chat.run_chat(cfg, [{"role": "user", "content": text}])
            reply = result.get("content")
    except Exception as e:  # noqa: BLE001 — LLM 失败降级到帮助提示
        logger.warning("飞书 WS LLM 调用失败: %s", e)

    if reply:
        _send_message(chat_id, reply)
        return

    # 3. 帮助提示
    _send_message(chat_id, "无法识别意图。试试：查所有股票 / 600519关联 / 图谱健康")


def _send_message(chat_id: str, text: str) -> None:
    """通过飞书 IM API 发送文本消息。

    用全局 default_config 凭据（与启动时一致），domain 走 config.feishu_domain。
    """
    if not chat_id:
        logger.warning("飞书 WS 回复跳过：chat_id 为空")
        return

    cfg = default_config
    if not cfg.feishu_app_id or not cfg.feishu_app_secret:
        logger.warning("飞书 WS 回复跳过：app_id/secret 未配置")
        return

    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        # domain：feishu（国内）/ lark（海外）；config 默认 "feishu"
        domain = cfg.feishu_domain if cfg.feishu_domain in ("feishu", "lark") else "feishu"

        cli = (
            lark.Client.builder()
            .app_id(cfg.feishu_app_id)
            .app_secret(cfg.feishu_app_secret)
            .domain(domain)
            .build()
        )

        body = (
            CreateMessageRequestBody()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
        )
        req = (
            CreateMessageRequest()
            .receive_id_type("chat_id")
            .request_body(body)
        )

        resp = cli.im.v1.message.create(req)
        if resp and resp.success():
            logger.info("飞书 WS 消息已发送到 %s…", chat_id[:15])
        else:
            logger.warning(
                "飞书 WS 消息发送失败: code=%s msg=%s",
                getattr(resp, "code", "?"),
                getattr(resp, "msg", "?"),
            )
    except Exception as e:  # noqa: BLE001 — 发送失败不能冒泡到工作线程
        logger.error("飞书 WS 消息发送异常: %s", e)
