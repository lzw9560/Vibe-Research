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


def backfill_t1_hit(t_date: str, t1_date: str) -> dict[str, Any]:
    """T+1 收盘后回填 T 日 watchlist 的 t1_zt hit 字段（累积二次确认数据）。

    流程：
    1. 读 {t_date}_watchlist.json（T 日生成的 watchlist）
    2. 查 zt_history[t1_date] 涨停 codes（T+1 日涨停池）
    3. 对每个 stock 回填 t1_zt = code in zt_codes_t1
    4. 写回 watchlist json（更新 t1_zt 字段）
    5. 返回命中率统计（vs 信号预期 4.34% 验证预测力）

    Args:
        t_date: T 日（watchlist 生成日，YYYY-MM-DD）
        t1_date: T+1 日（hit 判定日，YYYY-MM-DD）

    Returns:
        {status, t_date, t1_date, total, hit_count, hit_rate, expected_rate}
    """
    watchlist_path = _forecast_dir() / f"{t_date}_watchlist.json"
    if not watchlist_path.exists():
        _logger.warning("[S232] backfill: T 日 watchlist 不存在: %s", watchlist_path)
        return {"status": "no_watchlist", "t_date": t_date, "t1_date": t1_date}

    try:
        with open(watchlist_path, "r", encoding="utf-8") as f:
            watchlist = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("[S232] backfill: 读 watchlist 失败: %s", e)
        return {"status": "read_error", "t_date": t_date, "t1_date": t1_date, "error": str(e)}

    # 查 T+1 涨停 codes
    zt_codes_t1 = _load_zt_codes(t1_date)

    # 回填 t1_zt
    hit_count = 0
    stocks = watchlist.get("stocks", [])
    for stock in stocks:
        was_zt = stock["code"] in zt_codes_t1
        stock["t1_zt"] = was_zt
        if was_zt:
            hit_count += 1

    # 写回
    try:
        with open(watchlist_path, "w", encoding="utf-8") as f:
            json.dump(watchlist, f, ensure_ascii=False, indent=2, default=str)
    except OSError as e:
        _logger.warning("[S232] backfill: 写回 watchlist 失败: %s", e)
        return {"status": "write_error", "t_date": t_date, "t1_date": t1_date, "error": str(e)}

    total = len(stocks)
    hit_rate = hit_count / total if total else 0.0
    expected_rate = HIT_RATE  # 信号预期 4.34%

    _logger.info(
        "[S232] backfill T+1 hit: t_date=%s t1_date=%s total=%d hit=%d rate=%.2f%% (预期 %.2f%%)",
        t_date, t1_date, total, hit_count, hit_rate * 100, expected_rate * 100,
    )

    return {
        "status": "ok",
        "t_date": t_date,
        "t1_date": t1_date,
        "total": total,
        "hit_count": hit_count,
        "hit_rate": round(hit_rate, 4),
        "expected_rate": expected_rate,
        "deviation_pct": round((hit_rate - expected_rate) / expected_rate * 100, 2) if expected_rate else None,
    }


def _forecast_dir() -> Path:
    """.vibe-research/t1_forecast/ 目录。"""
    return Path(resolve_data_dir()) / "t1_forecast"


def render_hit_report(hit_result: dict[str, Any]) -> str:
    """人话报告——T+1 hit 回填结果 + 命中率 vs 预期。"""
    lines: list[str] = []
    if hit_result.get("status") != "ok":
        lines.append(f"⚠️ T+1 hit 回填失败：{hit_result.get('status')}")
        lines.append(f"T 日 {hit_result.get('t_date')} → T+1 {hit_result.get('t1_date')}")
        return "\n".join(lines)

    t_date = hit_result["t_date"]
    t1_date = hit_result["t1_date"]
    total = hit_result["total"]
    hit = hit_result["hit_count"]
    rate = hit_result["hit_rate"]
    expected = hit_result["expected_rate"]
    dev = hit_result.get("deviation_pct")

    lines.append(f"📊 T+1 hit 回填：{t_date} watchlist → {t1_date} 涨停判定")
    lines.append(f"总数 {total} 只 · 命中 {hit} 只 · 命中率 {rate*100:.2f}%")
    lines.append(f"信号预期 {expected*100:.2f}% · 偏差 {dev:+.1f}%")
    lines.append("")
    if total == 0:
        lines.append("T 日无 watchlist（市场未满足信号条件）")
    elif total < 30:
        # 样本不足：13×4.34%=0.56 预期命中，Poisson P(0;0.56)=57% 合理，单日命中率波动大不可信
        lines.append(
            f"⚠️ 样本不足（{total} < 30）——单日命中率波动大不可信"
            f"（13 只预期 0.56 涨停，0 命中 Poisson 概率 57% 合理），累积 60 天后验证"
        )
    elif dev is not None and dev < -30:
        lines.append(f"⚠️ 命中率显著低于预期（{dev:+.1f}%）——当前 regime 信号可能失效")
    elif dev is not None and dev > 30:
        lines.append(f"📈 命中率显著高于预期（{dev:+.1f}%）——当前 regime 信号增强")
    else:
        lines.append("命中率在预期区间内（±30%）——信号预测力稳定")
    lines.append("")
    lines.append("⚠️ 历史统计特征，市场有风险，累积 60 天后验证二次确认信号。")
    return "\n".join(lines)
