"""飞书 Bot 双向对话路由。

接收飞书消息事件 → 调 chat.py AI 对话层（含知识图谱工具）→ 回复。
复用 feishu_sender 的 App Bot 发送能力（send_to_feishu）。

事件订阅：飞书开放平台 → 事件订阅 → 消息接收（im.message.receive_v1），
把 `POST /api/feishu/bot` 配置为回调地址。

合规（CLAUDE.md §1 弱合规）：本路由只做「事件接入 → AI 对话 → 回复」
管道，不预置标的、不建议；方向性研判由 chat 层 SYSTEM_PROMPT 约束。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

import chat
from config import AssistantDefaultConfig as Config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["feishu_bot"])


# ── 飞书交互卡片格式化 ──────────────────────────────────────────────


def _format_kg_card(kg_result: Any, title: str = "投研知识图谱") -> dict:
    """把 KG 工具结果格式化成飞书交互卡片 JSON。

    支持 3 种 KG 结果：
    - kg_audit → `{by_type: {folder: count}, total_entities, vault_path}` 表格式
    - query_kg_entities → `list[dict]`（frontmatter 列表）
    - query_kg_relations → `{entity, relations: [{target, link}], total}` 关系列表

    返回飞书卡片 JSON（可作 `msg_type: "interactive"` 的 content 传入）。
    """
    elements: list[dict] = []

    # 1. kg_audit 结果 → 分类型计数
    if isinstance(kg_result, dict) and kg_result.get("by_type"):
        total = kg_result.get("total_entities", 0)
        elements.append({
            "tag": "div",
            "text": {"content": f"**总实体数**：{total}", "tag": "lark_md"},
        })
        elements.append({"tag": "hr"})
        for folder, count in sorted(kg_result["by_type"].items()):
            elements.append({
                "tag": "div",
                "text": {"content": f"- `{folder}`：{count}", "tag": "lark_md"},
            })

    # 2. query_kg_relations 结果 → 关系列表
    elif isinstance(kg_result, dict) and kg_result.get("relations") is not None:
        entity = kg_result.get("entity", "")
        total = kg_result.get("total", 0)
        elements.append({
            "tag": "div",
            "text": {"content": f"**实体**：{entity}（{total} 条关系）", "tag": "lark_md"},
        })
        elements.append({"tag": "hr"})
        relations = kg_result.get("relations", [])
        if not relations:
            elements.append({
                "tag": "div",
                "text": {"content": "_无关联实体_", "tag": "lark_md"},
            })
        for item in relations[:20]:
            target = item.get("target", "")
            elements.append({
                "tag": "div",
                "text": {"content": f"- {target}", "tag": "lark_md"},
            })
        if len(relations) > 20:
            elements.append({
                "tag": "div",
                "text": {"content": f"_…共 {total} 条，仅显示前 20_", "tag": "lark_md"},
            })

    # 3. query_kg_entities 结果 → 实体列表（list[dict]）
    elif isinstance(kg_result, list):
        if not kg_result:
            elements.append({
                "tag": "div",
                "text": {"content": "_无匹配实体_", "tag": "lark_md"},
            })
        for item in kg_result[:20]:
            code = item.get("code") or item.get("_filename", "")
            name = item.get("name") or item.get("title", "")
            elements.append({
                "tag": "div",
                "text": {"content": f"- `{code}` {name}", "tag": "lark_md"},
            })
        if len(kg_result) > 20:
            elements.append({
                "tag": "div",
                "text": {"content": f"_…共 {len(kg_result)} 条，仅显示前 20_", "tag": "lark_md"},
            })

    # 4. error dict 或未知结构 → 回退纯文本
    elif isinstance(kg_result, dict) and kg_result.get("error"):
        elements.append({
            "tag": "div",
            "text": {"content": f"❌ {kg_result['error']}", "tag": "lark_md"},
        })
    else:
        elements.append({
            "tag": "div",
            "text": {"content": f"```\n{json.dumps(kg_result, ensure_ascii=False, indent=2)[:2000]}\n```", "tag": "lark_md"},
        })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": "blue",
        },
        "elements": elements,
    }


# ── KG 直查（不经 LLM 的意图识别）──────────────────────────────────


def _direct_kg_lookup(text: str) -> Optional[dict]:
    """轻量意图识别 + KG 直查（不经 LLM）。

    复用 /direct 端点的识别逻辑，返回 KG 工具的原始结果 dict/list。
    无法识别意图时返回 None（调用方降级到 LLM 或报错）。

    用于：
    - 主路由 /api/feishu/bot 在 LLM 失败时降级
    - 流式端点 /api/feishu/bot/stream 第一步立刻返回 KG 结果
    """
    from ai.tools.registry import execute as exec_tool
    import re

    if not text:
        return None
    text = text.strip()

    # 图谱健康
    if text in ("健康", "图谱健康", "audit", "审查"):
        return exec_tool("kg_audit", {})

    # "600519 关联" / "查 600519 关系"
    code_match = re.search(r"(\d{6}|[A-Z]{1,5})\s*(关联|关系|relations)", text)
    if code_match:
        code = code_match.group(1)
        return exec_tool("query_kg_relations", {"entity_code": code, "entity_type": "stock"})

    # 裸 6 位代码（spec 2.1：re.search(r"\d{6}")）
    if re.search(r"\d{6}", text):
        code = re.search(r"(\d{6})", text).group(1)
        return exec_tool("query_kg_relations", {"entity_code": code, "entity_type": "stock"})

    # "查所有股票" / "查白酒行业"
    type_map = {
        "股票": "stock", "stock": "stock",
        "行业": "industry", "industry": "industry",
        "概念": "concept", "concept": "concept",
        "战法": "strategy", "strategy": "strategy",
        "数据源": "data_source", "data source": "data_source",
        "spec": "spec", "决策": "spec",
        "事件": "event", "event": "event",
    }
    detected_type = None
    for kw, t in type_map.items():
        if kw in text.lower():
            detected_type = t
            break

    if detected_type:
        industry_match = re.search(r"(\S+?)行业", text)
        if industry_match:
            industry = industry_match.group(1)
            return exec_tool("query_kg_entities", {
                "entity_type": detected_type,
                "filter_field": "industry",
                "filter_value": industry,
            })
        return exec_tool("query_kg_entities", {"entity_type": detected_type})

    return None


@router.post("/api/feishu/bot")
async def feishu_bot_webhook(request: Request) -> Dict[str, Any]:
    """飞书事件回调入口。

    - 首次配置回调时飞书发 `{"challenge": "xxx"}`，原样回显完成校验。
    - 正常事件：提取消息文本 → chat.run_chat（含 KG 工具）→ send_to_feishu 回复。

    简单实现：同步处理（先跑通，流式/异步队列后续优化）。
    签名校验：飞书 v2 事件用 `X-Lark-Signature` 头 + app_secret 做
    HMAC-SHA256；本地自托管且未配 secret 时跳过（不阻断功能）。
    """
    body = await request.json()

    # 1. challenge 校验（首次配置回调时飞书发 challenge）
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    # 2. 提取消息文本
    event = body.get("event", {}) or {}
    msg = event.get("message", {}) or {}
    content = msg.get("content", "{}")
    try:
        text = json.loads(content).get("text", "") if isinstance(content, str) else ""
    except (json.JSONDecodeError, TypeError):
        text = content if isinstance(content, str) else ""

    # 去掉 @机器人 的前缀（飞书 @ 消息文本含 @_user_xxx）
    if text:
        text = text.strip()
        # 飞书 @ 格式 @_user_1 后跟空格 + 实际内容
        text = text.split(" ", 1)[-1] if text.startswith("@_user") else text

    if not text:
        return {"ok": False, "reason": "empty text"}

    # 3. 调 AI 对话层（复用 chat.run_chat，TOOLS 含 query_kg_entities 等新工具）
    try:
        cfg = chat._get_env_llm_config()
        if not cfg.get("baseURL") or not cfg.get("apiKey") or not cfg.get("model"):
            return {
                "ok": False,
                "error": "后端未配置 VR_LLM_BASE_URL / VR_LLM_API_KEY / VR_LLM_MODEL",
            }
        result = chat.run_chat(cfg, [{"role": "user", "content": text}])
        reply = result.get("content", "") or "（AI 无回复）"
    except Exception as e:  # noqa: BLE001 — 对话失败回错误消息给用户
        logger.error("飞书 bot 对话失败: %s", e)
        reply = f"查询失败：{e}"

    # 4. 回复消息（用 feishu_sender 的 App Bot；send_to_feishu 用实例 chat_id）
    #
    # 回复策略（spec 2.3）：
    # - LLM 回复用纯文本（LLM 输出已是 markdown，send_to_feishu 支持）
    # - 若 LLM 失败但 KG 直查能答，用 _format_kg_card 格式化成飞书交互卡片
    try:
        from notification.senders.feishu_sender import FeishuSender

        config = Config()
        # 事件带来 chat_id 时覆盖实例默认（P2P / 群聊通用）
        event_chat_id = msg.get("chat_id") or ""
        if event_chat_id:
            config.feishu_chat_id = event_chat_id
        # 确保走 App Bot 路径（非 webhook）
        if not config.feishu_webhook_url:
            config.feishu_prefer_app_bot = True
        sender = FeishuSender(config)

        # KG 直查（不经 LLM）：意图能匹配时立刻可答，作 LLM 失败的降级
        kg_result = _direct_kg_lookup(text)
        if reply.startswith("查询失败") and kg_result is not None:
            # LLM 失败但 KG 能答 → 用飞书交互卡片
            card = _format_kg_card(kg_result, title="投研知识图谱")
            ok = sender.send_feishu_card(card)
        else:
            ok = sender.send_to_feishu(reply)
        if not ok:
            logger.warning("飞书 bot 回复发送未成功（send_to_feishu 返回 False）")
    except Exception as e:  # noqa: BLE001 — 回复失败不抛 5xx，回结构化错误
        logger.error("飞书 bot 回复失败: %s", e)
        return {"ok": False, "error": str(e)}

    return {"ok": True}


@router.post("/api/feishu/bot/test")
async def feishu_bot_test(payload: Dict[str, Any]) -> Dict[str, Any]:
    """测试 bot 对话（不经过飞书，直接调 chat + KG 工具）。

    用法：POST /api/feishu/bot/test  body={"text":"查所有股票"}
    用于验收 AI 对话层 + 新 KG 工具是否就绪，不触发飞书发送。
    """
    text = payload.get("text", "查所有股票")
    try:
        cfg = chat._get_env_llm_config()
        if not cfg.get("baseURL") or not cfg.get("apiKey") or not cfg.get("model"):
            return {
                "ok": False,
                "error": "后端未配置 VR_LLM_BASE_URL / VR_LLM_API_KEY / VR_LLM_MODEL",
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


@router.post("/api/feishu/bot/direct")
async def feishu_bot_direct(payload: Dict[str, Any]) -> Dict[str, Any]:
    """直接查 KG 工具（不经 LLM）。立刻可用，不依赖 LLM 配置。

    用法：
    POST /api/feishu/bot/direct  body={"text":"查所有股票"}
    POST /api/feishu/bot/direct  body={"text":"600519 关联"}
    POST /api/feishu/bot/direct  body={"text":"图谱健康"}

    飞书事件路由 /api/feishu/bot 在 LLM 不可用时降级调此逻辑。
    """
    text = (payload.get("text") or "").strip()

    # 简单意图识别（不经 LLM）
    from ai.tools.registry import execute as exec_tool

    if not text or text in ("健康", "图谱健康", "audit", "审查"):
        result = exec_tool("kg_audit", {})
        return {"ok": True, "action": "kg_audit", "result": result}

    # "600519 关联" / "查 600519 关系"
    import re
    code_match = re.search(r"(\d{6}|[A-Z]{1,5})\s*(关联|关系|relations)", text)
    if code_match:
        code = code_match.group(1)
        result = exec_tool("query_kg_relations", {"entity_code": code, "entity_type": "stock"})
        return {"ok": True, "action": "query_kg_relations", "entity": code, "result": result}

    # "查所有股票" / "查白酒行业"
    type_map = {
        "股票": "stock", "stock": "stock",
        "行业": "industry", "industry": "industry",
        "概念": "concept", "concept": "concept",
        "战法": "strategy", "strategy": "strategy",
        "数据源": "data_source", "data source": "data_source",
        "spec": "spec", "决策": "spec",
        "事件": "event", "event": "event",
    }
    detected_type = None
    for kw, t in type_map.items():
        if kw in text.lower():
            detected_type = t
            break

    if detected_type:
        # 查行业过滤 "白酒行业"
        industry_match = re.search(r"(\S+?)行业", text)
        if industry_match:
            industry = industry_match.group(1)
            result = exec_tool("query_kg_entities", {
                "entity_type": detected_type,
                "filter_field": "industry",
                "filter_value": industry,
            })
            return {"ok": True, "action": "query_kg_entities", "filter": f"industry={industry}", "result": result}
        result = exec_tool("query_kg_entities", {"entity_type": detected_type})
        return {"ok": True, "action": "query_kg_entities", "type": detected_type, "result": result}

    return {"ok": False, "error": "无法识别意图。试试：查所有股票 / 600519关联 / 图谱健康"}


@router.post("/api/feishu/bot/stream")
async def feishu_bot_stream(payload: Dict[str, Any]) -> Dict[str, Any]:
    """流式 bot 对话（先返回 KG 直查结果，LLM 回复异步推送）。

    用法：
    POST /api/feishu/bot/stream  body={"text":"600519 关联"}
    POST /api/feishu/bot/stream  body={"text":"查所有股票"}
    POST /api/feishu/bot/stream  body={"text":"图谱健康"}

    两阶段回复：
    - 第一步：立刻返回 KG 直查结果（不经 LLM），前端可即时渲染卡片
    - 第二步：异步调 LLM（若配置了），llm_reply 字段填充；未配置或失败时
      source="kg_only"，前端只用 KG 结果

    合规：KG 直查只返回图谱客观数据（实体元数据/关系链接），方向性研判
    由 LLM 在 SYSTEM_PROMPT 约束下给出。
    """
    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text 不能为空"}

    # 第一步：立刻返回 KG 直查结果（不经 LLM）
    kg_result = _direct_kg_lookup(text)

    # 第二步：异步调 LLM（如果配置了）
    llm_reply: Optional[str] = None
    try:
        cfg = chat._get_env_llm_config()
        if cfg.get("baseURL") and cfg.get("apiKey") and cfg.get("model"):
            result = chat.run_chat(cfg, [{"role": "user", "content": text}])
            llm_reply = result.get("content")
    except Exception as e:  # noqa: BLE001 — LLM 不可用时只用 KG 结果
        logger.warning("飞书 bot stream LLM 调用失败，降级为 kg_only: %s", e)

    return {
        "ok": True,
        "text": text,
        "kg_result": kg_result,
        "kg_card": _format_kg_card(kg_result) if kg_result is not None else None,
        "llm_reply": llm_reply,
        "source": "both" if llm_reply else ("kg_only" if kg_result is not None else "llm_only"),
    }


__all__ = ["router"]
