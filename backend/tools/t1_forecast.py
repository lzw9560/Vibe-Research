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


def _generate_from_preloaded(
    target_date: str,
    all_bars: dict[str, list[dict]],
    zt_codes_t: set[str],
) -> dict[str, Any]:
    """核心筛选逻辑（用 preloaded data，不加载 DB）——backfill_history 复用避重复加载。

    筛选：T 日有 kline bar + NOT 在 zt_history[T]（未涨停）+ turn>TURN_THRESHOLD
          + vr5>VR5_THRESHOLD + 非 ST
    """
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

    return {
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
    watchlist = _generate_from_preloaded(target_date, all_bars, zt_codes_t)
    _logger.info("[S232] T+1 watchlist %s: %d 只（turn>20% & vr5>2，观察池非买入信号）",
                 target_date, watchlist["count"])
    return watchlist


def backfill_history(end_date: str, days: int = 60) -> dict[str, Any]:
    """历史 backfill——一次性加载 kline+zt，loop N 天生成 watchlist+回填 hit（避重复加载）。

    照 [[backfill-historical-data-before-waiting]] 教训：累积验证数据优先回补历史非等。
    1 次加载 kline（~13s）+ N 天纯计算 loop（秒级），vs N 次 generate_t1_watchlist（N×13s）。

    Args:
        end_date: 回填最后 T 日（YYYY-MM-DD，需 zt_history 有此日数据）
        days: 回填天数（T 日数量，默认 60）

    Returns:
        {days, total, hit, hit_rate, expected_rate, daily: [{t, t1, total, hit, rate}]}
    """
    # 一次性加载 kline（最慢，~13s）
    all_bars = _load_kline_bars()
    # 一次性加载 zt_history 全量（date -> set(code)）
    zt_db = _zt_db_path()
    zt_by_date: dict[str, set[str]] = {}
    if zt_db.exists():
        conn = sqlite3.connect(str(zt_db))
        try:
            for d, c in conn.execute("SELECT date, code FROM zt_history"):
                zt_by_date.setdefault(d, set()).add(c)
        finally:
            conn.close()

    # 交易日历（zt_history 有数据的日期，排序）
    cal = sorted(zt_by_date.keys())
    if end_date not in cal:
        _logger.warning("[S232] backfill_history: end_date %s 不在 zt_history", end_date)
        return {"status": "no_end_date", "end_date": end_date}
    end_idx = cal.index(end_date)
    start_idx = max(0, end_idx - days)
    pairs = [(cal[i], cal[i + 1]) for i in range(start_idx, end_idx) if i + 1 < len(cal)]

    _forecast_dir().mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    th = ts = 0
    for t, t1 in pairs:
        zt_t = zt_by_date.get(t, set())
        zt_t1 = zt_by_date.get(t1, set())
        wl = _generate_from_preloaded(t, all_bars, zt_t)
        # 回填 t1_zt
        hit = 0
        for s in wl["stocks"]:
            s["t1_zt"] = s["code"] in zt_t1
            if s["t1_zt"]:
                hit += 1
        # 持久化（含 t1_zt）
        path = _forecast_dir() / f"{t}_watchlist.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(wl, f, ensure_ascii=False, indent=2, default=str)
        except OSError as e:  # noqa: BLE001
            _logger.warning("[S232] backfill_history 持久化失败 %s: %s", t, e)

        total = len(wl["stocks"])
        rate = hit / total if total else 0.0
        results.append({"t": t, "t1": t1, "total": total, "hit": hit, "rate": round(rate, 4)})
        th += hit
        ts += total

    overall_rate = th / ts if ts else 0.0
    _logger.info(
        "[S232] backfill_history: %d 天 %d 只信号股，命中 %d，命中率 %.2f%%（预期 %.2f%%）",
        len(results), ts, th, overall_rate * 100, HIT_RATE * 100,
    )
    return {
        "status": "ok",
        "days": len(results),
        "total": ts,
        "hit": th,
        "hit_rate": round(overall_rate, 4),
        "expected_rate": HIT_RATE,
        "deviation_pct": round((overall_rate - HIT_RATE) / HIT_RATE * 100, 2) if HIT_RATE else None,
        "daily": results,
    }


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


def t1_exit_optimization(end_date: str, days: int = 180, gap_lo: float = -5, gap_hi: float = -2) -> dict[str, Any]:
    """退出规则优化——网格搜索 T+2 stop/take 找最优 exit（归因"纪律创正 EV"指引）。

    归因 workflow 确认用户赚最可能靠"止盈止损纪律"（breakout +0.36% p=0.041）。
    close_ev 戳破 T+2 open 卖全负——但 T+2 盘中 stop/take 可能改善（避开低开亏损/捕获 high）。

    entry: T+1 open 买（gap 已知后，低开-5%~-2% 组）
    exit: T+2 盘中 stop/take 触发或 T+2 close 卖
    - stop: T+1 open × (1 - stop%)，T+2 low 触及则 stop 卖
    - take: T+1 open × (1 + take%)，T+2 high 触及则 take 卖
    - 都不触发：T+2 close 卖
    - stop/take 都触发：保守假设 stop 先（T+2 低开先 stop）
    """
    all_bars = _load_kline_bars()
    zt_by_date: dict[str, set[str]] = {}
    zt_db = _zt_db_path()
    if zt_db.exists():
        conn = sqlite3.connect(str(zt_db))
        try:
            for d, c in conn.execute("SELECT date, code FROM zt_history"):
                zt_by_date.setdefault(d, set()).add(c)
        finally:
            conn.close()

    cal = sorted(zt_by_date.keys())
    if end_date not in cal:
        return {"status": "no_end_date"}
    date_idx = {d: i for i, d in enumerate(cal)}
    end_idx = cal.index(end_date)
    pairs = [(cal[i], cal[i + 1]) for i in range(max(0, end_idx - days), end_idx) if i + 1 < len(cal)]

    records: list[dict[str, Any]] = []
    for t, t1 in pairs:
        zt_t = zt_by_date.get(t, set())
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        t2 = cal[t1_idx + 1]
        wl = _generate_from_preloaded(t, all_bars, zt_t)
        for s in wl["stocks"]:
            code = s["code"]
            t_close = s["close"]
            if t_close is None:
                continue
            bars = all_bars.get(code, [])
            t1_bar = next((b for b in bars if b.get("date") == t1), None)
            if not t1_bar:
                continue
            t1_open = t1_bar.get("open")
            if t1_open is None or t1_open == 0:
                continue
            gap = (t1_open - t_close) / t_close * 100
            if not (gap_lo <= gap < gap_hi):
                continue
            # 排除 T+1 一字买不进
            zt_limit = 0.2 if code.startswith(("sz30", "sh68")) else 0.1
            if t1_open >= t_close * (1 + zt_limit) * 0.999:
                continue
            t2_bar = next((b for b in bars if b.get("date") == t2), None)
            if not t2_bar:
                continue
            t2_open = t2_bar.get("open")
            t2_high = t2_bar.get("high")
            t2_low = t2_bar.get("low")
            t2_close = t2_bar.get("close")
            if None in (t2_open, t2_high, t2_low, t2_close):
                continue
            records.append({
                "code": code, "t1_open": t1_open,
                "t2_open": t2_open, "t2_high": t2_high, "t2_low": t2_low, "t2_close": t2_close,
            })

    # 网格 stop/take
    stops = [0.0, -0.03, -0.05, -0.08]  # 0=不止损
    takes = [0.0, 0.03, 0.05, 0.08, 0.10]  # 0=不止盈
    grid: list[dict[str, Any]] = []
    for stop in stops:
        for take in takes:
            rets = []
            for r in records:
                entry = r["t1_open"]
                stop_price = entry * (1 + stop) if stop < 0 else None
                take_price = entry * (1 + take) if take > 0 else None
                # T+2 触发判断（保守：stop 优先 if both trigger）
                stop_triggered = stop_price is not None and r["t2_low"] <= stop_price
                take_triggered = take_price is not None and r["t2_high"] >= take_price
                if stop_triggered and stop_price is not None:
                    exit_price = stop_price  # stop 卖
                elif take_triggered and take_price is not None:
                    exit_price = take_price  # take 卖
                else:
                    exit_price = r["t2_close"]  # hold 到 T+2 close
                ret = (exit_price - entry) / entry * 100
                rets.append(ret)
            n = len(rets)
            ev = sum(rets) / n if n else 0
            grid.append({
                "stop": f"{stop*100:+.0f}%", "take": f"{take*100:+.0f}%",
                "n": n, "ev": round(ev, 2), "positive": ev > 0,
            })

    grid.sort(key=lambda x: x["ev"], reverse=True)
    baseline = next((g for g in grid if g["stop"] == "+0%" and g["take"] == "+0%"), None)
    best = grid[0] if grid else None
    _logger.info("[S232] t1_exit_optimization: %d 记录, baseline EV=%s, best EV=%s",
                len(records),
                f"{baseline['ev']:.2f}%" if baseline else "N/A",
                f"{best['ev']:.2f}%" if best else "N/A")
    return {
        "status": "ok", "total_records": len(records),
        "baseline": baseline, "best": best,
        "grid": grid[:10],  # top 10
    }


def t1_gap_analysis(end_date: str, days: int = 180) -> dict[str, Any]:
    """T+1 gap 二次确认分析——按 T+1 开盘 gap 分组验证命中率 + EV。

    二次确认逻辑：T 日 watchlist 信号股（turn>20%+vr5>2 未涨停），T+1 开盘 gap
    已知后决定买入。按 gap 分组（低开/平开/高开），每组命中率 + EV（涨停价卖 vs
    T+1 open 买）。若某组 EV > 0 或命中率 >8.5%（盈亏平衡），找到正 EV 择时——
    把 blanket 负 EV（-0.87%）转正。

    Args:
        end_date: 回填最后 T 日
        days: 回填天数（默认 180）

    Returns:
        {baseline, buckets: [{bucket, n, hit, rate, ev}], total_records}
    """
    all_bars = _load_kline_bars()
    zt_db = _zt_db_path()
    zt_by_date: dict[str, set[str]] = {}
    if zt_db.exists():
        conn = sqlite3.connect(str(zt_db))
        try:
            for d, c in conn.execute("SELECT date, code FROM zt_history"):
                zt_by_date.setdefault(d, set()).add(c)
        finally:
            conn.close()

    cal = sorted(zt_by_date.keys())
    if end_date not in cal:
        return {"status": "no_end_date", "end_date": end_date}
    end_idx = cal.index(end_date)
    pairs = [(cal[i], cal[i + 1]) for i in range(max(0, end_idx - days), end_idx) if i + 1 < len(cal)]

    date_idx = {d: i for i, d in enumerate(cal)}
    records: list[dict[str, Any]] = []
    for t, t1 in pairs:
        zt_t = zt_by_date.get(t, set())
        zt_t1 = zt_by_date.get(t1, set())
        # T+2（A 股 T+1 制度：T+1 open 买当日不能卖，最早 T+2 卖）
        t1_idx = date_idx.get(t1)
        if t1_idx is None or t1_idx + 1 >= len(cal):
            continue
        t2 = cal[t1_idx + 1]
        zt_t2 = zt_by_date.get(t2, set())
        wl = _generate_from_preloaded(t, all_bars, zt_t)
        for s in wl["stocks"]:
            code = s["code"]
            t_close = s["close"]
            if t_close is None:
                continue
            bars = all_bars.get(code, [])
            t1_bar = next((b for b in bars if b.get("date") == t1), None)
            if not t1_bar:
                continue
            t1_open = t1_bar.get("open")
            t1_close = t1_bar.get("close")
            if t1_open is None or t1_close is None or t1_open == 0:
                continue
            t2_bar = next((b for b in bars if b.get("date") == t2), None)
            if not t2_bar or t2_bar.get("open") is None:
                continue
            t2_open = t2_bar["open"]
            gap = (t1_open - t_close) / t_close * 100
            was_zt_t1 = code in zt_t1
            was_zt_t2 = code in zt_t2
            # 涨停价：主板 10%，创业板/科创板 20%（A 股涨停相对前日 close）
            zt_limit = 0.2 if code.startswith(("sz30", "sh68")) else 0.1
            zt_price_t1 = t_close * (1 + zt_limit)  # T+1 涨停价相对 T close
            # 排除 T+1 一字涨停（t1_open 接近涨停价=买不进，V1 假 edge 根因 R1）
            if t1_open >= zt_price_t1 * 0.999:
                continue  # 一字涨停买不进，排除（避 over-credit）
            # 诚实 EV 口径（high-return workflow 戳破 open_ev 日内泄漏）：
            # close_ev: T+1 close 买 T+2 open 卖（post-confirmation，隔离 T+1 日内泄漏）
            # T+2 涨停保守按 t2_open 卖（不 over-credit 涨停价，V1 根因 R2 exit 一字 over-credit）
            close_ev = ((t2_open - t1_close) / t1_close * 100) if t1_close else 0.0
            records.append({
                "code": code, "t": t, "t1": t1, "t2": t2, "gap": round(gap, 2),
                "was_zt_t1": was_zt_t1, "was_zt_t2": was_zt_t2,
                "ret": round(close_ev, 2),  # close_ev 诚实口径（替代旧 open_ev）
                "close_ev": round(close_ev, 2),
            })

    # 分组（gap buckets）
    bucket_defs = [
        ("低开<-5%", lambda g: g < -5),
        ("低开-5%~-2%", lambda g: -5 <= g < -2),
        ("平开-2%~+2%", lambda g: -2 <= g <= 2),
        ("高开+2%~+5%", lambda g: 2 < g <= 5),
        ("高开>+5%", lambda g: g > 5),
    ]
    buckets: list[dict[str, Any]] = []
    for name, fn in bucket_defs:
        sub = [r for r in records if fn(r["gap"])]
        n = len(sub)
        hit = sum(1 for r in sub if r["was_zt_t2"])
        rate = hit / n if n else 0.0
        ev = sum(r["ret"] for r in sub) / n if n else 0.0
        buckets.append({
            "bucket": name, "n": n, "hit": hit,
            "rate": round(rate, 4), "ev": round(ev, 2),
            "positive_ev": ev > 0,
        })

    total_n = len(records)
    total_hit = sum(1 for r in records if r["was_zt_t2"])
    total_ev = sum(r["ret"] for r in records) / total_n if total_n else 0.0
    baseline = {
        "bucket": "全样本(T+1 open 买 T+2 卖, 不筛 gap)",
        "n": total_n, "hit": total_hit,
        "rate": round(total_hit / total_n, 4) if total_n else 0,
        "ev": round(total_ev, 2),
    }

    _logger.info(
        "[S232] t1_gap_analysis: %d 记录，baseline EV=%.2f%%，正 EV 组数=%d",
        total_n, total_ev, sum(1 for b in buckets if b["ev"] > 0),
    )
    return {
        "status": "ok",
        "days": len(pairs),
        "total_records": total_n,
        "baseline": baseline,
        "buckets": buckets,
        "breakeven_rate": 0.085,  # 盈亏平衡命中率（winner +12.48% 盖 loser -1.16%）
    }
