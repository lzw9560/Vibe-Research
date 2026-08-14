# -*- coding: utf-8 -*-
"""S066 Phase 2 P2-4 产业资本 + 事件类因子。

spec §8/P2-4 数据需求：
- 大股东增减持（akshare stock_ggcx_em / stock_shareholder_change_ths）
- 业绩预告（akshare stock_yjyg_em）
- 解禁数据（akshare stock_share_unlock_em）
- 公告分类（利好/利空/风险提示，走 LLM 辅助）
- 除权除息日历（backend/data/ex_dividend_calendar.json）

事件类因子是**定性上下文层**，不是量化因子——与资讯雷达（§10）同定位。
不参与策略分计算，在候选卡片上标注事件标签，辅助用户决策。

数据源：akshare（免费，包东财 HTTP API，不走 RSS）。
akshare 不可达 → 返空列表（不崩，标注"事件数据未取得"）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_EX_DIVIDEND_PATH = Path(__file__).resolve().parent.parent / "data" / "ex_dividend_calendar.json"
_EX_DIVIDEND_CACHE: dict | None = None


# ===========================================================================
# 数据结构
# ===========================================================================

@dataclass(frozen=True)
class EventFactor:
    """事件类因子（spec §8/P2-4）。"""
    event_type: str          # 业绩预告 / 增持 / 减持 / 解禁 / 除权除息
    event_date: str          # 事件日期
    event_label: str         # 利好 / 利空 / 风险提示 / 中性
    detail: str             # 事件详情
    impact_score: float     # 影响分（-1.0 ~ +1.0，正=利好，负=利空）


@dataclass(frozen=True)
class EventContext:
    """个股事件类上下文。"""
    code: str
    events: list[EventFactor]
    has_upcoming_ex_dividend: bool
    ex_dividend_note: str = ""


# ===========================================================================
# 业绩预告（spec §8 stock_yjyg_em）
# ===========================================================================

def fetch_earnings_forecast(code: str) -> list[EventFactor]:
    """业绩预告（akshare stock_yjyg_em）。

    返回事件因子列表（利好/利空）。
    akshare 不可达 → 返空列表。
    """
    try:
        import akshare as ak
        df = ak.stock_yjyg_em(date="20261231")  # 最新报告期
        if df is None or df.empty:
            return []
        row = df[df["股票代码"] == code]
        if row.empty:
            return []
        r = row.iloc[0]
        forecast_type = str(r.get("业绩预告类型", ""))
        change_pct = r.get("业绩预告变动幅度", 0)
        detail = f"{forecast_type}，变动幅度 {change_pct}%"

        # 业绩预告类型 → 影响分
        impact_map = {
            "预增": (1.0, "利好"),
            "续盈": (0.3, "中性偏正"),
            "略增": (0.5, "利好"),
            "扭亏": (0.8, "利好"),
            "预减": (-0.8, "利空"),
            "续亏": (-0.5, "利空"),
            "首亏": (-1.0, "利空"),
            "略减": (-0.3, "利空"),
        }
        impact, label = impact_map.get(forecast_type, (0.0, "中性"))

        announce_date = str(r.get("公告日期", ""))[:10]
        return [EventFactor(
            event_type="业绩预告",
            event_date=announce_date,
            event_label=label,
            detail=detail,
            impact_score=impact,
        )]
    except Exception:
        return []


# ===========================================================================
# 大股东增减持（spec §8）
# ===========================================================================

def fetch_shareholder_change(code: str) -> list[EventFactor]:
    """大股东增减持（akshare stock_shareholder_change_ths）。

    akshare 无 stock_ggcx_em → 用 stock_shareholder_change_ths 替代。
    返回事件因子列表。
    """
    try:
        import akshare as ak
        df = ak.stock_shareholder_change_ths(symbol=code)
        if df is None or df.empty:
            return []
        events: list[EventFactor] = []
        for _, r in df.head(5).iterrows():
            change_type = str(r.get("变动类型", r.get("变动方向", "")))
            change_shares = r.get("变动股数", r.get("变动股份数量", 0))
            change_date = str(r.get("变动日期", r.get("公告日", "")))[:10]

            if "增持" in change_type:
                label = "利好"
                impact = 0.6
            elif "减持" in change_type:
                label = "利空"
                impact = -0.6
            else:
                label = "中性"
                impact = 0.0

            events.append(EventFactor(
                event_type="增减持",
                event_date=change_date,
                event_label=label,
                detail=f"{change_type}，变动 {change_shares} 股",
                impact_score=impact,
            ))
        return events
    except Exception:
        return []


# ===========================================================================
# 解禁数据（spec §8）
# ===========================================================================

def fetch_share_unlock(code: str) -> list[EventFactor]:
    """限售解禁（spec §8）。

    akshare 无 stock_share_unlock_em → 用 astock lockup_expiry 替代。
    返回未来 90 天的解禁事件。
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from astock import lockup_expiry
        data = lockup_expiry(code, forward_days=90)
        events: list[EventFactor] = []
        for item in data.get("upcoming", []):
            unlock_date = item.get("date", "")
            shares = item.get("shares", 0)
            ratio = item.get("ratio", 0)
            # 解禁比例 > 5% → 风险提示
            if ratio and ratio > 5:
                label = "风险提示"
                impact = -0.7
            elif ratio and ratio > 1:
                label = "利空"
                impact = -0.3
            else:
                label = "中性"
                impact = -0.1

            events.append(EventFactor(
                event_type="解禁",
                event_date=unlock_date,
                event_label=label,
                detail=f"解禁 {shares} 股（占比 {ratio}%）",
                impact_score=impact,
            ))
        return events
    except Exception:
        return []


# ===========================================================================
# 除权除息日历（spec §8/P2-4）
# ===========================================================================

def _load_ex_dividend_calendar() -> dict:
    """加载除权除息日历。文件不存在返空 dict。"""
    global _EX_DIVIDEND_CACHE
    if _EX_DIVIDEND_CACHE is not None:
        return _EX_DIVIDEND_CACHE
    try:
        _EX_DIVIDEND_CACHE = json.loads(_EX_DIVIDEND_PATH.read_text(encoding="utf-8"))
    except Exception:
        _EX_DIVIDEND_CACHE = {}
    return _EX_DIVIDEND_CACHE


def check_ex_dividend(code: str, trade_date: str, forward_days: int = 30) -> tuple[bool, str]:
    """检查个股在持仓期间是否有除权除息（spec §16.11）。

    返回 (是否有除权除息, 说明)。
    数据缺失 → (False, "除权除息日历未取得")。
    """
    cal = _load_ex_dividend_calendar()
    if not cal:
        return False, "除权除息日历未取得"

    events = cal.get("events", [])
    if not events:
        return False, "无除权除息数据"

    try:
        target_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError:
        return False, "日期格式错误"

    end_dt = target_dt + timedelta(days=forward_days)
    for event in events:
        if event.get("code") != code:
            continue
        try:
            event_dt = datetime.strptime(event.get("date", ""), "%Y-%m-%d")
            if target_dt <= event_dt <= end_dt:
                return True, f"{event.get('date')} 除权除息（{event.get('type', '')}）"
        except ValueError:
            continue

    return False, "持仓期间无除权除息"


# ===========================================================================
# 事件上下文聚合
# ===========================================================================

def build_event_context(code: str, trade_date: str | None = None) -> EventContext:
    """聚合个股事件类上下文（spec §8/P2-4）。

    合并：业绩预告 + 增减持 + 解禁 + 除权除息。
    各数据源独立拉取，任一失败不阻断其他（降级不崩）。
    """
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    events: list[EventFactor] = []

    # 业绩预告
    events.extend(fetch_earnings_forecast(code))
    # 增减持
    events.extend(fetch_shareholder_change(code))
    # 解禁
    events.extend(fetch_share_unlock(code))

    # 除权除息
    has_ex_div, ex_note = check_ex_dividend(code, trade_date)

    return EventContext(
        code=code,
        events=events,
        has_upcoming_ex_dividend=has_ex_div,
        ex_dividend_note=ex_note,
    )


# ===========================================================================
# 公告分类（LLM 辅助，spec §10.5）
# ===========================================================================

def classify_announcement_llm(announcement_text: str, chat_fn: Any | None = None) -> str:
    """公告分类（利好/利空/风险提示）——LLM 辅助。

    spec §10.5：LLM 调用走系统已有 chat 层（backend/chat.py）。
    本函数提供接口，实际 LLM 调用由调用方注入 chat_fn。

    无 chat_fn → 关键词粗筛降级（复用 news_radar_context.classify_announcement）。
    """
    if chat_fn is None:
        # 降级到关键词粗筛
        from strategies.news_radar_context import classify_announcement
        return classify_announcement(announcement_text)

    try:
        prompt = f"""请将以下A股公告分类为：预增/扭亏/重组/回购/增持/风险提示/中性。
只返回分类标签，不要解释。

公告内容：{announcement_text}"""
        result = chat_fn(prompt)
        return str(result).strip() if result else "中性"
    except Exception:
        # LLM 调用失败 → 降级关键词粗筛
        from strategies.news_radar_context import classify_announcement
        return classify_announcement(announcement_text)
