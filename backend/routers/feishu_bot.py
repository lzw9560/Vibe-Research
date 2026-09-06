"""飞书 Bot 双向对话路由。

接收飞书消息事件 → 调 chat.py AI 对话层（含知识图谱工具）→ 回复。
复用 feishu_sender 的 App Bot 发送能力（send_to_feishu）。

事件订阅：飞书开放平台 → 事件订阅 → 消息接收（im.message.receive_v1），
把 `POST /api/feishu/bot` 配置为回调地址。

合规（CLAUDE.md §1 弱合规）：本路由只做「事件接入 → AI 对话 → 回复」
管道，不预置标的、不建议；方向性研判由 chat 层 SYSTEM_PROMPT 约束。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

import chat
from config import AssistantDefaultConfig as Config

logger = logging.getLogger(__name__)
router = APIRouter(tags=["feishu_bot"])


# ── 飞书交互卡片格式化 ──────────────────────────────────────────────


_OBSIDIAN_REVIEWS_URI = (
    "obsidian://open?vault=Obsidian%20Vault"
    "&file=10_Reference/investing/reviews"
)


def _button_action(actions: list[dict]) -> dict:
    """构造飞书卡片 action 元素（按钮组容器）。"""
    return {"tag": "action", "actions": actions}


def _url_button(text: str, url: str, btn_type: str = "primary") -> dict:
    """跳转 URL 按钮（不触发回调）。"""
    return {
        "tag": "button",
        "text": {"content": text, "tag": "plain_text"},
        "type": btn_type,
        "url": url,
    }


def _callback_button(text: str, value: dict, btn_type: str = "primary") -> dict:
    """触发回调的按钮（value 由 /bot/callback 解析）。"""
    return {
        "tag": "button",
        "text": {"content": text, "tag": "plain_text"},
        "type": btn_type,
        "value": value,
    }


def _format_kg_card(kg_result: Any, title: str = "投研知识图谱") -> dict:
    """把 KG 工具结果格式化成飞书交互卡片 JSON（含按钮 + Obsidian URI 跳转）。

    支持 3 种 KG 结果：
    - kg_audit → `{by_type: {folder: count}, total_entities, vault_path}` 表格式
      + "查看完整审查" 按钮（Obsidian URI 跳转 reviews 文件夹）
    - query_kg_entities → `list[dict]`（frontmatter 列表）
      + "查前 N 只行情" 按钮（回调 query_quote）
    - query_kg_relations → `{entity, relations: [{target, link}], total}` 关系列表

    返回飞书卡片 JSON（顶层 config/header/elements，可作
    `msg_type: "interactive"` 的 content 传入 send_feishu_card）。
    """
    elements: list[dict] = []

    # 1. kg_audit 结果 → 分类型计数 + 审查跳转按钮
    if isinstance(kg_result, dict) and kg_result.get("by_type"):
        total = kg_result.get("total_entities", 0)
        elements.append({
            "tag": "div",
            "text": {"content": f"**总实体数**：{total}", "tag": "lark_md"},
        })
        elements.append({"tag": "hr"})
        for folder, count in sorted(kg_result["by_type"].items()):
            emoji = "✅" if count > 0 else "❌"
            elements.append({
                "tag": "div",
                "text": {"content": f"{emoji} `{folder}`：{count}", "tag": "lark_md"},
            })
        # 按钮：跳 Obsidian 审查目录
        elements.append(_button_action([
            _url_button("查看完整审查", _OBSIDIAN_REVIEWS_URI),
        ]))

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
                "text": {"content": f"- → {target}", "tag": "lark_md"},
            })
        if len(relations) > 20:
            elements.append({
                "tag": "div",
                "text": {"content": f"_…共 {total} 条，仅显示前 20_", "tag": "lark_md"},
            })

    # 3. query_kg_entities 结果 → 实体列表（list[dict]）+ 查行情按钮
    elif isinstance(kg_result, list):
        if not kg_result:
            elements.append({
                "tag": "div",
                "text": {"content": "_无匹配实体_", "tag": "lark_md"},
            })
        shown = kg_result[:20]
        for item in shown:
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
        # 按钮：查前 N 只行情（回调 query_quote）
        quote_codes = [
            item.get("code") for item in shown
            if isinstance(item, dict) and item.get("code")
        ][:5]
        if quote_codes:
            elements.append(_button_action([
                _callback_button(
                    f"查前 {len(quote_codes)} 只行情",
                    {"action": "query_quote", "codes": quote_codes},
                ),
            ]))

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
        "config": {"wide_screen_mode": True, "enable_forward": False},
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
    # 回复策略（spec 2.3 + 优化）：
    # - KG 直查能答 → 用 _format_kg_card 格式化成飞书交互卡片（含按钮）
    # - KG 不可答、LLM 成功 → 用纯文本（LLM 输出已是 markdown）
    # - LLM 失败但 KG 能答 → 用卡片（与第一条合并，自然降级）
    # - LLM 失败且 KG 不可答 → 文本报错
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

        # KG 直查（不经 LLM）：意图能匹配时立刻可答
        kg_result = _direct_kg_lookup(text)
        llm_failed = reply.startswith("查询失败")

        if kg_result is not None:
            # KG 可答 → 卡片（含按钮 + Obsidian URI 跳转）
            # 若 LLM 也成功，把 LLM 回答追加到卡片尾部作补充上下文
            title = "投研知识图谱"
            if not llm_failed and reply:
                # LLM 也答了：卡片标题区分一下，但主体仍是 KG 数据
                title = "投研知识图谱（含 AI 解读）"
            card = _format_kg_card(kg_result, title=title)
            if not llm_failed and reply:
                # 在卡片末尾追加 AI 解读块
                card["elements"].append({"tag": "hr"})
                card["elements"].append({
                    "tag": "div",
                    "text": {"content": f"**AI 解读**：{reply[:1500]}", "tag": "lark_md"},
                })
            ok = sender.send_feishu_card(card)
        elif not llm_failed:
            # KG 不可答、LLM 成功 → 纯文本
            ok = sender.send_to_feishu(reply)
        else:
            # LLM 失败且 KG 不可答 → 文本报错
            ok = sender.send_to_feishu(reply)
        if not ok:
            logger.warning("飞书 bot 回复发送未成功（send_to_feishu/send_feishu_card 返回 False）")
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
async def feishu_bot_stream(payload: Dict[str, Any]):
    """真流式 bot 对话（SSE）。

    用法：
    POST /api/feishu/bot/stream  body={"text":"600519 关联"}
    POST /api/feishu/bot/stream  body={"text":"查所有股票"}
    POST /api/feishu/bot/stream  body={"text":"图谱健康"}

    事件流（每个事件形如 `data: <json>\n\n`）：
    - `{"type":"kg","data":<kg_result>}`  立刻：KG 直查结果（不经 LLM）
    - `{"type":"llm","data":"<reply>"}`  异步：LLM 回答（若配置可用）
    - `{"type":"error","data":"<msg>"}`  LLM 调用异常
    - `{"type":"done"}`                  结束标记

    合规：KG 直查只返回图谱客观数据（实体元数据/关系链接），方向性
    研判由 LLM 在 SYSTEM_PROMPT 约束下给出。
    """
    from fastapi.responses import StreamingResponse

    text = (payload.get("text") or "").strip()

    async def event_stream():
        # 事件 1：KG 直查（立刻）
        try:
            kg_result = _direct_kg_lookup(text)
            if kg_result is not None:
                payload_kg = {"type": "kg", "data": kg_result}
                # 带上格式化好的卡片，前端可即时渲染
                try:
                    payload_kg["card"] = _format_kg_card(kg_result)
                except Exception as e:  # noqa: BLE001 — 卡片格式化失败不阻断流
                    logger.warning("stream KG 卡片格式化失败: %s", e)
                yield f"data: {json.dumps(payload_kg, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 — KG 工具异常不阻断后续 LLM
            logger.warning("stream KG 直查异常: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'data': f'kg: {e}'}, ensure_ascii=False)}\n\n"

        # 事件 2：LLM 回答（异步等待）
        try:
            cfg = chat._get_env_llm_config()
            if cfg.get("baseURL") and cfg.get("apiKey") and cfg.get("model"):
                # run_chat 是同步阻塞调用，丢到线程池避免阻塞事件循环
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, lambda: chat.run_chat(cfg, [{"role": "user", "content": text}])
                )
                reply = result.get("content", "") or ""
                if reply:
                    yield f"data: {json.dumps({'type': 'llm', 'data': reply}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 — LLM 不可用时只推 error 不阻断 done
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"

        # 事件 3：结束
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # text 为空时仍返回 SSE（带 error + done），保持流式契约一致
    if not text:
        async def empty_stream():
            yield f"data: {json.dumps({'type': 'error', 'data': 'text 不能为空'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/feishu/bot/callback")
async def feishu_bot_callback(request: Request) -> Dict[str, Any]:
    """飞书交互卡片按钮回调。

    飞书配置：开放平台 → 事件订阅 → 卡片交互回调地址指向本端点。
    按钮点击时飞书 POST 一个 `{"action": {"value": {...}, ...}}` body。

    支持 action：
    - ``{"action": "query_quote", "codes": ["600519", ...]}``
      → 调 query_quote 工具，返回更新后的卡片 JSON（飞书会替换原卡片）

    返回 ``{"card": <new_card>}`` 让飞书原地更新卡片内容；未知 action 时
    返回结构化错误（卡片不变）。

    合规：query_quote 返回行情客观数据（价格/涨跌），不做方向性建议。
    """
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001 — 非合法 JSON 回 400 结构化错误
        return {"ok": False, "error": f"invalid json: {e}"}

    # 飞书回调可能把 action 包在 challenge 校验里（与事件回调一致）
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    action = body.get("action", {}) or {}
    value = action.get("value", {}) or {}
    action_name = value.get("action")

    if action_name == "query_quote":
        codes = value.get("codes", [])
        if not codes:
            return {"ok": False, "error": "codes 为空"}
        try:
            from ai.tools.registry import execute as exec_tool

            result = exec_tool("query_quote", {"codes": codes})
        except Exception as e:  # noqa: BLE001 — 工具执行失败回结构化错误
            logger.error("callback query_quote 失败: %s", e)
            return {"ok": False, "error": str(e)}
        card = _format_kg_card(result, title=f"{len(codes)} 只股票行情")
        return {"card": card}

    logger.warning("callback 未知 action: %s", action_name)
    return {"ok": False, "error": f"未知 action: {action_name}"}


__all__ = ["router"]
