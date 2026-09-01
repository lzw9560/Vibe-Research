"""S005 中长线价值选股漏斗路由。

合规：响应仅客观数据+骨架，无方向结论词、无参考价位；L4 文字交用户 AI。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from value_funnel import funnel, quality, models
from value_funnel.sources import l1_scan, l3_analysis, l4_deep_skeleton

router = APIRouter(tags=["value-funnel"])

# 运行结果内存缓存（run_id -> ValueFunnelResult）。单进程足够；多进程需换 Redis。
_RUNS: dict[str, models.ValueFunnelResult] = {}
_RUN_TTL = 3600  # 简化：不做主动过期


class ScanReq(BaseModel):
    direction: str
    top_n: int = 60


class RunReq(BaseModel):
    direction: str
    stage: str = "all"  # L1/L2/L3/L4/all
    top_n_l1: int = 60
    top_n_l4: int = 3


class LLMConfig(BaseModel):
    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str = ""


# ---------- L1 扫描 ----------

@router.post("/api/value-funnel/scan")
def scan(req: ScanReq):
    """按行业/主题/指数扫描候选。"""
    try:
        return {"candidates": l1_scan.scan_universe(req.direction, req.top_n)}
    except Exception as e:
        raise HTTPException(400, f"扫描失败: {e}")


# ---------- 运行漏斗 ----------

@router.post("/api/value-funnel/run")
def run(req: RunReq):
    """运行价值漏斗（L1→L2→L3→L4 或单层）。"""
    if req.stage not in ("L1", "L2", "L3", "L4", "all"):
        raise HTTPException(400, "stage 须为 L1/L2/L3/L4/all")
    try:
        result = funnel.run_value_funnel(req.direction, req.stage,
                                         req.top_n_l1, req.top_n_l4)
    except Exception as e:
        raise HTTPException(500, f"漏斗运行失败: {e}")
    _RUNS[result.run_id] = result
    return result


@router.get("/api/value-funnel/result")
def get_result(run_id: str):
    r = _RUNS.get(run_id)
    if not r:
        raise HTTPException(404, "run_id 不存在或已过期")
    return r


@router.get("/api/value-funnel/layers")
def get_layers(run_id: str):
    r = _RUNS.get(run_id)
    if not r:
        raise HTTPException(404, "run_id 不存在或已过期")
    return r.layers


# ---------- 单只去劣 + 护城河 ----------

@router.get("/api/value-funnel/{code}/quality")
def get_quality(code: str):
    """单只标的去劣7条 + 双口径通过率 + 护城河代理。"""
    try:
        return quality.compute_quality(code)
    except Exception as e:
        raise HTTPException(500, f"去劣计算失败: {e}")


# ---------- L3 精细分析骨架 ----------

@router.get("/api/value-funnel/{code}/analysis")
def get_analysis(code: str):
    try:
        name = funnel._name_of(code)
        return l3_analysis.build_analysis_skeleton(code, name)
    except Exception as e:
        raise HTTPException(500, f"分析骨架构建失败: {e}")


# ---------- S108：财报异常 5 信号（新浪三表 → FinancialPeriod → detect_anomalies）----------

@router.get("/api/value-funnel/{code}/anomaly")
def get_anomaly(code: str):
    """单只财报异常 5 信号（塞渠道/积压/利润质量/capex突增/非经常占比）。

    S108：新浪三表 fetch_merged_periods → detect_anomalies。不足 2 期标 inapplicable（不臆造）。
    数据源新浪 urllib（非 em_get），单只按需触发不进 L2 全量（请求风暴防线）。

    S134：返体加 ``data_status``——period_count==0 时 peek sina_financial breaker：
    fresh OPEN → 'sina_breaker_open'（区分"Sina 暂不可用"vs"真无财报"），
    否则 'missing'；有 periods → 'ok'。诚实缝（不臆造"有数据"）。
    """
    from circuit_breaker import get_breaker
    try:
        from data.sources.sina_financial import fetch_merged_periods
        from value_funnel.anomaly import detect_anomalies
        periods = fetch_merged_periods(code)
        assessment = detect_anomalies(periods)
        if len(periods) >= 2:
            status = "ok"
        elif get_breaker("sina_financial").peek_state().value == "open":
            status = "sina_breaker_open"
        else:
            status = "missing"
        return {
            "data": assessment.model_dump(mode="json"),
            "period_count": len(periods),
            "data_status": status,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"异常信号计算失败: {e}") from e


# ---------- L4 四大师 → AI 产出文字 ----------

@router.post("/api/value-funnel/{code}/deep-ai")
def deep_ai(code: str, llm: LLMConfig):
    """调用户 AI 填四大师文字。
    支持两条出口：
      - 订阅接入 provider=cli-claude（调本机 claude CLI，免 key，用订阅额度）
      - API 接入（OpenAI 兼容，需 baseURL+apiKey）
    依赖 S001 修复后的 chat 层。"""
    name = funnel._name_of(code)
    skeleton = l4_deep_skeleton.build_deep_skeleton(code, name)
    cfg = llm.model_dump()
    provider = str(cfg.get("provider", ""))
    is_cli = provider.startswith("cli-")

    if is_cli:
        # 订阅接入：检测本机 CLI
        try:
            import cli_runtime
            kind = provider[4:]
            if not cli_runtime.detect_cli(kind):
                raise HTTPException(400, f"未检测到「{kind}」CLI，请先安装并登录，或改用 API 接入")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"CLI 检测失败: {e}")
    else:
        # API 接入：缺字段用环境变量兜底
        try:
            import chat as chat_layer
            env = chat_layer._get_env_llm_config()
            for k in ("baseURL", "apiKey", "model"):
                if not cfg.get(k) and env.get(k):
                    cfg[k] = env[k]
        except Exception:
            pass
        if not cfg.get("apiKey") or not cfg.get("baseURL"):
            raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」配置，或用订阅接入(cli-claude)")

    master_block = "\n".join(
        f"【{p.master}】框架:{p.framework}；引导问题:{'；'.join(p.key_questions)}"
        for p in skeleton.perspectives)
    user_msg = (
        f"对股票 {code}（{name}）按四大师视角各写一段深度分析（每段约 200-300 字），"
        f"严格分块，每段以【巴菲特】【芒格】【段永平】【李录】开头。只陈述客观事实与相对位置，"
        f"不给买卖/目标价建议。四大师框架与引导问题：\n{master_block}")
    try:
        import chat as chat_layer
        runner = chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream
        text = ""
        for ev in runner(cfg, [{"role": "user", "content": user_msg}], ""):
            if ev.get("type") == "delta":
                # API 用 delta，CLI 用 text —— 两者都取
                text += ev.get("delta") or ev.get("text") or ""
            elif ev.get("type") == "error":
                skeleton.perspectives[0].ai_text = f"AI 失败: {ev.get('message')}"
                skeleton.ai_pending = True
                return skeleton
        _fill_perspectives(skeleton, text)
        skeleton.ai_pending = False
        return skeleton
    except Exception as e:
        skeleton.perspectives[0].ai_text = f"AI 调用异常: {e}"
        skeleton.ai_pending = True
        return skeleton


def _fill_perspectives(skeleton: models.DeepAnalysisSkeleton, text: str) -> None:
    """按【大师】标记切分 text 填入各 perspective.ai_text。"""
    import re
    names = ["巴菲特", "芒格", "段永平", "李录"]
    # 找每个标记位置
    positions = []
    for n in names:
        idx = text.find(f"【{n}】")
        if idx >= 0:
            positions.append((idx, n))
    positions.sort()
    for i, (idx, n) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk = text[idx:end].strip()
        for p in skeleton.perspectives:
            if p.master == n:
                p.ai_text = chunk
                break
    # 未切到任何标记 → 全文塞第一个
    if not positions and text:
        skeleton.perspectives[0].ai_text = text
