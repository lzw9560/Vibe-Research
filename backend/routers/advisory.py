# -*- coding: utf-8 -*-
"""S042 统一持仓建议引擎 API（R5）+ S067 P3 端点超时降级。

GET /api/advisory/summary → 三场景建议汇总（推荐/自选/持仓）。
教育研究式口吻，非交易指令（CLAUDE.md §1.1 弱合规）。
"""
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from strategies.position_advisor import advisory_summary, advise_recommendations, advise_watchlist

router = APIRouter(tags=["advisory"])

# S067 P3：端点超时上限（秒）——超时返回已计算部分 + partial=true
_ENDPOINT_TIMEOUT = 15.0


@router.get("/api/advisory/summary")
async def advisory_summary_endpoint(
    limit: int = Query(20, ge=1, le=50, description="推荐标的取 top N"),
) -> Dict[str, Any]:
    """三场景建议汇总（recommendations + watchlist + holdings）。

    每条建议含 win_rate / win_rate_source（backtest_90d / synthetic / none）/
    matched_strategy / reasons / risk_notes + 免责声明。

    S067 P3：15s 超时降级——超时返回已计算部分 + partial=true + disclaimer，
    不让前端卡死。超时部分标 timed_out。回退不重算（避免再次阻塞）。
    """
    try:
        result = await asyncio.wait_for(advisory_summary(limit), timeout=_ENDPOINT_TIMEOUT)
        return result
    except asyncio.TimeoutError:
        # 超时降级：返回空 + partial=true，不重算（重算会再次阻塞事件循环）
        return {
            "recommendations": [],
            "watchlist": [],
            "holdings": [],
            "partial": True,
            "timed_out": True,
            "timeout_seconds": _ENDPOINT_TIMEOUT,
            "disclaimer": "历史统计特征，市场有风险，不构成投资建议。端点超时，建议稍后重试。",
            "note": f"端点 {_ENDPOINT_TIMEOUT}s 超时，三场景均未完成。可能是回测冷启动或数据源慢，请稍后重试。",
        }
    except Exception as e:  # noqa: BLE001 — 建议引擎异常返 502，不泄露栈
        raise HTTPException(502, f"建议引擎异常：{e}") from e


# S216 Advisory 顾问团 grill-me 后端集成：6-lens 对抗审查（参考 CLAUDE.md §44 ≥6 lens + grill-me skill）。
# 后端跑不了 Claude skill（grill-me 是 Claude Code 的），但 chat.py 有 LLM 接入（VR_LLM_*），
# 跑 6-lens prompt 模板返结果。6 视角：方法论/数据/过拟合/执行/风险/一致性。
_LENS_NAMES = ("methodology", "data_quality", "overfit", "execution", "risk", "consistency")
_LENS_LABELS = {
    "methodology": "方法论（统计方法/窗口/样本/多重比较）",
    "data_quality": "数据质量（PIT/生存偏差/缺失）",
    "overfit": "过拟合（参数调过/样本内偏差）",
    "execution": "执行（可交易性/成本/滑点）",
    "risk": "风险（尾部/regime 依赖）",
    "consistency": "一致性（跨窗口/跨样本）",
}


def _build_grill_prompt(topic: str, context: str) -> list[dict]:
    """构建 6-lens 对抗审查 prompt——每 lens 独立 refute-default 视角审 topic。

    返 OpenAI messages 格式。system 设对抗审查角色（默认 refute），user 给 topic+context+6 lens。
    """
    lens_list = "\n".join(f"- {n}: {_LENS_LABELS[n]}" for n in _LENS_NAMES)
    return [
        {
            "role": "system",
            "content": (
                "你是投研对抗审查者。对用户给的研究 topic 跑 6 视角对抗审查，"
                "每视角默认反驳（refute-default）——找该视角下的漏洞/风险/反例。"
                "不迎合用户，按证据走。每视角返 {verdict: pass/warn/fail, evidence: 一句依据}。"
                "最后给 synthesis: 综合结论（几视角通过/几警告/几失败 + 是否可推进）。"
                "用中文返 JSON: {lenses:[{name,verdict,evidence}], synthesis}。"
            ),
        },
        {
            "role": "user",
            "content": f"topic: {topic}\n\ncontext: {context}\n\n6 lens:\n{lens_list}",
        },
    ]


@router.post("/api/advisory/grill")
async def advisory_grill(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S216 Advisory 顾问团 grill——后端跑 6-lens 对抗审查 prompt 返结果。

    走 chat.py LLM 接入（VR_LLM_BASE_URL/API_KEY/MODEL）。缺 LLM 配置返
    {data_status: "missing"} 不臆造。6-lens：方法论/数据/过拟合/执行/风险/一致性。
    私有数据（持仓/研报/API key）不进 prompt——只 topic+context（用户传的研究描述）。
    """
    topic = str(payload.get("topic", "")).strip()
    context = str(payload.get("context", "")).strip()
    if not topic:
        raise HTTPException(400, "topic 必填")

    try:
        import chat  # noqa: PLC0415
        cfg = chat._get_env_llm_config()
        if not cfg.get("baseURL") or not cfg.get("apiKey") or not cfg.get("model"):
            return {
                "data": {
                    "data_status": "missing",
                    "note": "VR_LLM_BASE_URL/API_KEY/MODEL 未配，顾问团 grill 无法跑 LLM",
                    "lenses": [],
                    "synthesis": None,
                }
            }
        messages = _build_grill_prompt(topic, context)
        result = chat._call_llm(cfg, messages, use_tools=False)
        # 解析 LLM 返 JSON——content 在 choices[0].message.content
        content = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        # 尝试 parse JSON（LLM 可能返 markdown 包裹）
        import json  # noqa: PLC0415
        import re  # noqa: PLC0415
        json_match = re.search(r"\{[\s\S]*\}", content)
        parsed = None
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                parsed = None
        if not parsed:
            # LLM 没返合法 JSON——返 raw content 不臆造结构
            return {
                "data": {
                    "data_status": "ok",
                    "lenses": [],
                    "synthesis": None,
                    "raw_content": content,
                    "note": "LLM 未返合法 JSON，raw_content 供人工核",
                }
            }
        return {
            "data": {
                "data_status": "ok",
                "lenses": parsed.get("lenses", []),
                "synthesis": parsed.get("synthesis"),
                "topic": topic,
            }
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"顾问团 grill 异常：{e}") from e


__all__ = ["router"]
