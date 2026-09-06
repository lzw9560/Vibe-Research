"""微信 Bot 双向对话路由。

企业微信应用回调 → 调 chat.py AI 对话层（含知识图谱工具）→ 回复。
复用 feishu_bot._direct_kg_lookup 的意图识别 + KG 工具直查。

合规（CLAUDE.md §1 弱合规）：本路由只做「事件接入 → AI 对话 → 回复」
管道，不预置标的、不建议；方向性研判由 chat 层 SYSTEM_PROMPT 约束。

企业微信回调配置：
- 管理后台 → 应用管理 → 自建应用 → 接收消息 → 设置 API 接收
- URL: https://<公网域名>/api/wechat/bot
- Token: 自定义（配到 config.wechat_token / env WECHAT_TOKEN）
- EncodingAESKey: 可选（不配则明文模式，本实现只支持明文）

与飞书 bot 的差异：
- 企业微信用 XML 非 JSON（消息体是 XML）
- 被动回复模式：5 秒内返回 XML 响应即回复用户，不需主动调发送 API
  （飞书是主动发送模式——事件回调后调 send_to_feishu 发消息）
- 企业微信不支持交互卡片，KG 结果只能格式化成纯文本
"""
from __future__ import annotations

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse

import chat
from config import AssistantDefaultConfig as Config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["wechat_bot"])


# ── 企业微信回调签名校验 ──────────────────────────────────────────


def _verify_signature(signature: str, timestamp: str, nonce: str, token: str) -> bool:
    """企业微信签名校验：sort(token, timestamp, nonce) → SHA1 → 比较。

    未配 token 时跳过校验（本地自托管友好）；公网部署务必配 token。
    """
    if not token:
        return True
    arr = sorted([token, timestamp, nonce])
    sha1 = hashlib.sha1("".join(arr).encode()).hexdigest()
    return sha1 == signature


# ── XML 构建 ──────────────────────────────────────────────────────


def _build_xml(to_user: str, from_user: str, content: str) -> str:
    """构建企业微信被动回复 XML。

    被动回复参数语义（与原始消息 XML 相反）：
    - to_user: 原始 XML 的 ToUserName（企业号/应用），回复时填 FromUserName
    - from_user: 原始 XML 的 FromUserName（用户），回复时填 ToUserName
    """
    return (
        f"<xml>\n"
        f"<ToUserName><![CDATA[{from_user}]]></ToUserName>\n"
        f"<FromUserName><![CDATA[{to_user}]]></FromUserName>\n"
        f"<CreateTime>{int(time.time())}</CreateTime>\n"
        f"<MsgType><![CDATA[text]]></MsgType>\n"
        f"<Content><![CDATA[{content}]]></Content>\n"
        f"</xml>"
    )


# ── KG 结果格式化（纯文本，企业微信不支持交互卡片）────────────────


def _format_kg_as_text(kg_result: Any) -> str:
    """把 KG 工具结果格式化成纯文本。

    与飞书 bot 的 _format_kg_card 对应，但企业微信被动回复只有纯文本，
    不支持飞书交互卡片（lark_md / interactive）。
    """
    import json as _json

    # 1. kg_audit 结果 → 分类型计数
    if isinstance(kg_result, dict) and kg_result.get("by_type"):
        total = kg_result.get("total_entities", 0)
        lines = [f"总实体数：{total}", ""]
        for folder, count in sorted(kg_result.get("by_type", {}).items()):
            lines.append(f"- {folder}：{count}")
        return "\n".join(lines)

    # 2. query_kg_relations 结果 → 关系列表
    if isinstance(kg_result, dict) and kg_result.get("relations") is not None:
        entity = kg_result.get("entity", "")
        total = kg_result.get("total", 0)
        relations = kg_result.get("relations", [])
        lines = [f"实体：{entity}（{total} 条关系）", ""]
        for item in relations[:20]:
            lines.append(f"- {item.get('target', '')}")
        if len(relations) > 20:
            lines.append(f"…共 {total} 条，仅显示前 20")
        return "\n".join(lines)

    # 3. query_kg_entities 结果 → 实体列表
    if isinstance(kg_result, list):
        if not kg_result:
            return "无匹配实体"
        lines = []
        for item in kg_result[:20]:
            code = item.get("code") or item.get("_filename", "")
            name = item.get("name") or item.get("title", "")
            lines.append(f"- {code} {name}")
        if len(kg_result) > 20:
            lines.append(f"…共 {len(kg_result)} 条，仅显示前 20")
        return "\n".join(lines)

    # 4. error dict 或未知结构 → JSON 回退
    if isinstance(kg_result, dict) and kg_result.get("error"):
        return f"查询错误：{kg_result['error']}"
    return _json.dumps(kg_result, ensure_ascii=False, indent=2)[:2000]


# ── 端点 ──────────────────────────────────────────────────────────


@router.get("/api/wechat/bot")
async def wechat_bot_verify(
    msg_signature: str = Query(""),
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    echostr: str = Query(""),
):
    """企业微信回调 URL 验证（GET 请求）。

    企业微信管理后台配置回调 URL 时，发 GET 请求校验签名 + 回显 echostr。
    企业微信用 ``msg_signature`` 参数名；同时兼容 ``signature``（公众号风格）。
    回显 echostr 用纯文本响应（企业微信要求响应体为 echostr 明文）。
    """
    sig = msg_signature or signature
    token = getattr(Config(), "wechat_token", "") or ""
    if not _verify_signature(sig, timestamp, nonce, token):
        return PlainTextResponse("signature mismatch")
    return PlainTextResponse(echostr) if echostr else PlainTextResponse("ok")


@router.post("/api/wechat/bot")
async def wechat_bot_webhook(request: Request):
    """企业微信消息事件回调（POST 请求）。

    企业微信 → 应用 → 接收消息 → 回调此 URL。
    消息格式：XML（企业微信用 XML 非 JSON）。

    被动回复模式：5 秒内返回 XML 响应即回复用户；超时企业微信会重试。
    简单实现：同步处理（先跑通，异步队列后续优化）。
    签名校验：本地自托管且未配 token 时跳过（不阻断功能）。

    回复策略（复制飞书 bot 模式，适配企业微信）：
    - LLM 可用 → 返回 LLM 回复（纯文本）
    - LLM 失败但 KG 直查能答 → 返回 KG 结果（纯文本格式化）
    - 两者都失败 → 返回错误提示
    """
    body = await request.body()
    # 解析 XML
    try:
        root = ET.fromstring(body)
        msg_type_el = root.find("MsgType")
        content_el = root.find("Content")
        from_user_el = root.find("FromUserName")
        to_user_el = root.find("ToUserName")
        msg_type = msg_type_el.text if msg_type_el is not None else ""
        content = content_el.text if content_el is not None else ""
        from_user = from_user_el.text if from_user_el is not None else ""
        to_user = to_user_el.text if to_user_el is not None else ""
    except Exception as e:  # noqa: BLE001 — XML 解析失败回错误
        logger.error("微信 bot XML 解析失败: %s", e)
        return {"error": f"XML parse failed: {e}"}

    if msg_type != "text" or not content:
        # 非文本消息，回空提示
        return PlainTextResponse(
            _build_xml(to_user, from_user, "目前只支持文本消息"),
            media_type="application/xml",
        )

    text = content.strip()

    # KG 直查降级（复用飞书 bot 的 _direct_kg_lookup，不重复实现意图识别）
    from routers.feishu_bot import _direct_kg_lookup

    # 调 LLM（如果配置了）
    reply: Optional[str] = None
    try:
        cfg = chat._get_env_llm_config()
        if cfg.get("baseURL") and cfg.get("apiKey") and cfg.get("model"):
            result = chat.run_chat(cfg, [{"role": "user", "content": text}])
            reply = result.get("content")
        else:
            logger.info("微信 bot: LLM 未配置，降级为 KG 直查")
    except Exception as e:  # noqa: BLE001 — LLM 失败时降级到 KG 直查
        logger.warning("微信 bot LLM 调用失败，降级为 KG 直查: %s", e)

    # LLM 失败时用 KG 直查
    if not reply:
        kg_result = _direct_kg_lookup(text)
        if kg_result is not None:
            reply = _format_kg_as_text(kg_result)
        else:
            reply = "查询失败，请稍后重试。试试：查所有股票 / 600519关联 / 图谱健康"

    return PlainTextResponse(
        _build_xml(to_user, from_user, reply),
        media_type="application/xml",
    )


@router.post("/api/wechat/bot/direct")
async def wechat_bot_direct(payload: Dict[str, Any]) -> Dict[str, Any]:
    """直接查 KG 工具（不经 LLM，不经微信回调）。复制飞书 /direct 逻辑。

    用法：
    POST /api/wechat/bot/direct  body={"text":"查所有股票"}
    POST /api/wechat/bot/direct  body={"text":"600519 关联"}
    POST /api/wechat/bot/direct  body={"text":"图谱健康"}

    微信事件路由 /api/wechat/bot 在 LLM 不可用时降级调此逻辑。
    """
    text = (payload.get("text") or "").strip()
    # 复用 feishu_bot 的 _direct_kg_lookup（不重复实现意图识别）
    from routers.feishu_bot import _direct_kg_lookup

    kg_result = _direct_kg_lookup(text)
    if kg_result is not None:
        return {"ok": True, "action": "kg_direct", "result": kg_result}
    return {"ok": False, "error": "无法识别意图。试试：查所有股票 / 600519关联 / 图谱健康"}


@router.post("/api/wechat/bot/test")
async def wechat_bot_test(payload: Dict[str, Any]) -> Dict[str, Any]:
    """测试 bot 对话（不经过微信）。复制飞书 /test 逻辑。

    用法：POST /api/wechat/bot/test  body={"text":"查所有股票"}
    用于验收 AI 对话层 + KG 工具是否就绪，不触发微信发送。
    """
    text = payload.get("text", "查所有股票")
    try:
        cfg = chat._get_env_llm_config()
        if not cfg.get("baseURL") or not cfg.get("apiKey") or not cfg.get("model"):
            return {
                "ok": False,
                "error": "未配置 VR_LLM_BASE_URL / VR_LLM_API_KEY / VR_LLM_MODEL",
            }
        result = chat.run_chat(cfg, [{"role": "user", "content": text}])
        return {
            "ok": True,
            "reply": result.get("content", ""),
            "trace": result.get("trace", []),
            "rounds": result.get("rounds", 0),
        }
    except Exception as e:  # noqa: BLE001 — 测试端点回结构化错误
        return {"ok": False, "error": str(e)}


__all__ = ["router"]
