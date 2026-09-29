# -*- coding: utf-8 -*-
"""S232 T+1 涨停预测 watchlist 生成器——观察池工具非买入信号。

12-agent workflow（6 专家 + 6 对抗）确认：
- T 日有真信号：换手率>20% + 量比>2.0 → lift 5.28x（CI[4.38,6.35]x 干净排除 1.0，n=2428）
- 但交易 EV -0.87%/笔（t=-4.48 显著负）——95.6% 不涨停亏 -1.16% 淹没 4.4% 涨停 +12.48%
- 第 5 根因"稀有事件-输家拖累"：base rate 0.822% 太低，5x 集中度=4.4% 命中 < 8.5% 盈亏平衡
- 信号是波动率代理非方向预判：pct<-5 大跌 lift 2.06x vs pct 8-9.3 大涨 lift 2.57x（两端都预判涨停）

对抗 agent 戳破的诚实标注（避 V1 假 edge 覆辙）：
- vr5>2 增量仅 1.02x（turn>20% 单独 5.18x，加 vr5>2 后 5.28x）——5.28x 几乎全来自 turn>20% 单条件
- 信号选出"在场内博弈"的票（高波动），不涨停时崩得 11 倍狠（-1.15% vs base -0.10%）

定位（最高优先级）：观察池/研究工具，非交易信号。
不进 sizing 承重墙（违 risk_rules.py:565"⛔ 不碰 final_size"），不触发 journal.add_trade，
不自动下单。作 watchlist + 二次确认累积 60 天验证，试图把"负 EV blanket"转"正 EV 择时"。

跑法：cd backend && .venv/bin/python -c "from tools.t1_forecast import generate_t1_watchlist; print(generate_t1_watchlist('2026-09-29'))"
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from vr_paths import resolve_data_dir

_logger = logging.getLogger("vibe-research")

# 信号阈值（12-agent workflow 验证：turn>20% + vr5>2 lift 5.28x 最强）
TURN_THRESHOLD = 20.0  # 换手率 %
VR5_THRESHOLD = 2.0  # 5 日均量比

# 诚实状态（避 V1 假 edge 覆辙——用户误当 edge 重仓）
EDGE_STATUS = "weak-signal-EV-negative"
SIGNAL_LIFT = 5.28
SIGNAL_LIFT_CI = "[4.38, 6.35]x"
BASE_RATE = 0.00822  # 全样本 T+1 涨停 base rate 0.822%
HIT_RATE = 0.0434  # 信号命中率 4.34%
HONEST_CAVEAT = (
    "5.28x lift 真实统计显著（CI[4.38,6.35]x 排除 1.0），但交易 EV -0.87%/笔显著负"
    "——第 5 根因（稀有事件 0.82% base rate + 输家拖累：95.6% 不涨停亏 -1.16% 淹没 4.4% 涨停 +12.48%）。"
    "信号是波动率代理非方向预判（大涨大跌都预判涨停）。"
    "作 watchlist 观察池非买入信号，二次确认信号累积 60 天验证中。"
)


def _kline_db_path() -> Path:
    """baostock_kline_cache.db 路径（.vibe-research/）。"""
    return Path(resolve_data_dir()) / "baostock_kline_cache.db"


def _zt_db_path() -> Path:
    """zt_history.db 路径（.vibe-research/）。"""
    return Path(resolve_data_dir()) / "zt_history.db"


def _load_zt_codes(date: str) -> set[str]:
    """读 zt_history.db 某日涨停 codes（排除 T 日涨停股，天生避 survivorship + entry 溢价）。"""
    db = _zt_db_path()
    if not db.exists():
        _logger.warning("[S232] zt_history.db 不存在: %s", db)
        return set()
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute("SELECT code FROM zt_history WHERE date = ?", (date,))
        return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def _load_kline_bars() -> dict[str, list[dict]]:
    """读 baostock_kline_cache.db 全量 kline bars（code -> bars list，按 date 排序）。"""
    db = _kline_db_path()
    if not db.exists():
        _logger.warning("[S232] baostock_kline_cache.db 不存在: %s", db)
        return {}
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute("SELECT code, bars_json FROM kline")
        result: dict[str, list[dict]] = {}
        for code, bj in cur.fetchall():
            try:
                bars = json.loads(bj)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(bars, list) and bars:
                # 按 date 排序（baostock 返回已排序，但保险）
                result[code] = sorted(bars, key=lambda b: b.get("date", ""))
        return result
    finally:
        conn.close()


def _vol_ratio_5(sorted_bars: list[dict], idx: int) -> float | None:
    """T 日 volume / mean(prev 5 days volume)。idx = sorted_bars 中 T 日位置。

    前置不足 5 日 / 前置含 0 量 / T 日无量 → None（不臆造）。
    """
    if idx < 5:
        return None
    tbar = sorted_bars[idx]
    vol = tbar.get("volume")
    if not vol:
        return None
    prev = sorted_bars[idx - 5:idx]
    pv = [b.get("volume") for b in prev]
    if any(v is None or v == 0 for v in pv):
        return None
    avg5 = sum(pv) / 5.0
    if avg5 == 0:
        return None
    return vol / avg5


def generate_t1_watchlist(target_date: str) -> dict[str, Any]:
    """生成 T+1 涨停预测 watchlist（观察池非买入信号）。

    筛选：T 日有 kline bar + NOT 在 zt_history[T]（未涨停，避 entry 溢价 + survivorship）
          + turn>TURN_THRESHOLD + vr5>VR5_THRESHOLD + 非 ST

    Args:
        target_date: T 日 YYYY-MM-DD

    Returns:
        watchlist dict{date, signal, signal_lift, signal_lift_ci, base_rate, hit_rate,
                       edge_status, honest_caveat, count, stocks[]}
        stocks[] 含 code/name/turn/vr5/pctChg/close/high/low/amount
                 + 二次确认字段（t1_zt/t1_auction/t1_seal_time/confirmed 初始 None）
    """
    zt_codes_t = _load_zt_codes(target_date)
    all_bars = _load_kline_bars()
    _logger.info("[S232] 加载 %d codes kline，T 日涨停池 %d codes",
                len(all_bars), len(zt_codes_t))

    stocks: list[dict[str, Any]] = []
    for code, sorted_bars in all_bars.items():
        # 找 T 日 bar
        tbar = None
        tbar_idx = -1
        for i, b in enumerate(sorted_bars):
            if b.get("date") == target_date:
                tbar = b
                tbar_idx = i
                break
        if tbar is None:
            continue
        # 排除 T 日涨停股（天生避 survivorship + entry 涨停价溢价）
        if code in zt_codes_t:
            continue
        # 排除 ST（涨停 5% 口径不同）——baostock 存 isST 为字符串 "0"/"1"（非整数），
        # 字符串 "0" 是 truthy，不能用 `if tbar.get("isST"):` 判断（会误过滤所有非 ST 股，CRITICAL bug）
        if tbar.get("isST") in ("1", 1, True):
            continue
        turn = tbar.get("turn")
        if turn is None or turn <= TURN_THRESHOLD:
            continue
        vr5 = _vol_ratio_5(sorted_bars, tbar_idx)
        if vr5 is None or vr5 <= VR5_THRESHOLD:
            continue
        pct = tbar.get("pctChg")
        stocks.append({
            "code": code,
            "name": code,  # baostock 无 name 字段，用 code（前端可查 basic_info 补）
            "turn": round(turn, 2),
            "vr5": round(vr5, 2),
            "pctChg": round(pct, 2) if pct is not None else None,
            "close": tbar.get("close"),
            "high": tbar.get("high"),
            "low": tbar.get("low"),
            "amount": tbar.get("amount"),
            # 二次确认字段（累积 60 天验证，初始 None）
            "t1_zt": None,  # T+1 是否涨停（T+1 收盘后回填）
            "t1_auction": None,  # 二次确认：竞价状态（低开/高开/平开）
            "t1_seal_time": None,  # 二次确认：封单时间
            "confirmed": None,  # 二次确认是否触发
        })

    watchlist = {
        "date": target_date,
        "signal": "turn>20% & vr5>2",
        "signal_lift": SIGNAL_LIFT,
        "signal_lift_ci": SIGNAL_LIFT_CI,
        "base_rate": BASE_RATE,
        "hit_rate": HIT_RATE,
        "edge_status": EDGE_STATUS,
        "honest_caveat": HONEST_CAVEAT,
        "count": len(stocks),
        "stocks": stocks,
    }
    _logger.info("[S232] T+1 watchlist %s: %d 只（turn>20% & vr5>2，观察池非买入信号）",
                 target_date, len(stocks))
    return watchlist


def render_watchlist_report(watchlist: dict[str, Any]) -> str:
    """人话报告——watchlist + 诚实标注（观察池非买入信号）。"""
    lines: list[str] = []
    lines.append(f"📅 {watchlist['date']} T+1 涨停预测 watchlist（观察池）")
    lines.append(
        f"信号：{watchlist['signal']}（lift {watchlist['signal_lift']}x "
        f"{watchlist['signal_lift_ci']}，命中率 {watchlist['hit_rate']*100:.2f}% "
        f"vs base rate {watchlist['base_rate']*100:.3f}%）"
    )
    lines.append(f"数量：{watchlist['count']} 只")
    lines.append("")
    lines.append(f"⚠️ {watchlist['honest_caveat']}")
    lines.append("")
    if watchlist["stocks"]:
        lines.append("观察池（非买入信号，二次确认累积验证中）：")
        for s in watchlist["stocks"][:20]:  # 前 20 只
            lines.append(
                f"  {s['code']} turn={s['turn']}% vr5={s['vr5']} "
                f"pct={s['pctChg']}% close={s['close']}"
            )
        if len(watchlist["stocks"]) > 20:
            lines.append(f"  ... 共 {len(watchlist['stocks'])} 只")
    else:
        lines.append("今日无信号股（市场未满足 turn>20% & vr5>2 条件）")
    lines.append("")
    lines.append("⚠️ 历史统计特征，市场有风险，真钱仓位与止损你最终决策。")
    return "\n".join(lines)
