# -*- coding: utf-8 -*-
"""combo 每日飞书提醒（2026-10-29 建，2026-11-08 FALSIFIED 后 daily 推送已 disable）。

⚠️ combo_5d edge 已 FALSIFIED 2026-11-08（9 专家 panel 10 角度证伪：real-exec t_nw=1.487 FAIL
/ permutation p=0.47 / live 101 settled mean -3.649%）。weight 0.3→0.0 止血，paper tracking
保留 60 天 settle 收尾（~2026-12-19）。combo_daily_notify cron enabled=0，此模块不再 daily 推送。

历史逻辑保留供复现（cron 50 18，load_combo_5d_today top-20 mode=filtered + gate + push_feishu）。
gate（FROZEN 阈值 2026-10-27，amount 口径）：breadth>40% AND 小盘decile 5d>0 → ON。
combo 真 alpha = universe 小盘 premium 非选股 edge（见 memory combo-edge-falsified-expert-panel-2026-11-08）。
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from pathlib import Path

bp = str(Path(__file__).resolve().parents[1])  # backend/
if bp not in sys.path:
    sys.path.insert(0, bp)

from tools.commander_runner import load_combo_5d_today, push_feishu  # noqa: E402
from vr_paths import resolve_data_dir  # noqa: E402

KLINE_DB = (
    resolve_data_dir() / "baostock_kline_cache.db"
)  # 项目根 .vibe-research/（parents[1]=backend/.vibe-research 是 4096 stub，compute_gate 查 no such table kline 就是这 bug，2026-10-30 戳破）


def compute_gate(date: str | None = None) -> dict:
    """算 gate：breadth>0.4 AND 小盘decile past5>0（FROZEN amount 口径）。

    复用 _audit_combo_winrate.py gate_on 逻辑 + ashare_regime_monitor FROZEN 阈值。
    返回 {viable, breadth, small_5d, n}。
    """
    conn = sqlite3.connect(str(KLINE_DB))
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    by_date: dict = {}
    for code, bj in rows:
        try:
            bars = json.loads(bj)
        except Exception:
            continue
        if len(bars) < 65:
            continue
        idx = None
        if date:
            for i in range(len(bars) - 1, -1, -1):
                bd = bars[i].get("date", "")
                if bd == date:
                    idx = i
                    break
                if bd < date:
                    break
        else:
            idx = len(bars) - 1
        if idx is None or idx < 60:
            continue
        prev_c = float(bars[idx - 1].get("close", 0) or 0)
        c = float(bars[idx].get("close", 0) or 0)
        amt = float(bars[idx].get("amount", 0) or 0)
        if not prev_c or not c or not amt:
            continue
        ma60 = statistics.mean(float(bars[j].get("close", 0) or 0) for j in range(idx - 60, idx))
        if not ma60:
            continue
        past5_c = float(bars[idx - 5].get("close", 0) or 0)
        past5 = (c - past5_c) / past5_c if past5_c else 0.0
        by_date[code] = {"up": c > ma60, "amt": amt, "past5": past5}
    if not by_date:
        return {"viable": False, "reason": "no_data", "breadth": None, "small_5d": None, "n": 0}
    breadth = sum(1 for x in by_date.values() if x["up"]) / len(by_date)
    srt = sorted(by_date.values(), key=lambda x: x["amt"])
    dec = max(1, len(srt) // 10)
    sm5 = statistics.mean(x["past5"] for x in srt[:dec])
    viable = breadth > 0.4 and sm5 > 0
    return {
        "viable": viable,
        "n": len(by_date),
        "breadth": round(breadth * 100, 1),
        "small_5d": round(sm5 * 100, 2),
    }


def main() -> None:
    picks = load_combo_5d_today(mode="filtered", top_n=20)
    if not picks:
        print("combo: 当日无 picks（universe 不足或 cache 未刷新到收盘）")
        return
    sig_date = picks[0].get("date", "")
    gate = compute_gate(sig_date)
    viable = gate.get("viable", False)
    lines = [
        f"🎯 combo-5d 每日提醒 {sig_date}",
        "",
        "⚠️ baostock EOD 滞后：信号可能 D-1（昨日收盘），今日 09:25 已过则明日买（1 天滞后，combo 选 D 信号 D+1 买）",
        "",
        f"【gate 状态】{'✅ ON 可交易' if viable else '⛔ OFF 不交易（纸面跟踪）'}",
        f"  市场宽度 {gate.get('breadth', '?')}%（>40% 才 ON）| 小盘5d {gate.get('small_5d', '?')}%（>0 才 ON）",
        "",
        f"【今日 top-20 候选】（去涨停，5日持有 nostop，次日 09:25 集合竞价买）",
    ]
    for i, p in enumerate(picks, 1):
        pos_1pct = p["amount"] * 100  # 1%ADV 万元（amount亿×1e8×0.01=amount×1e6元=amount×100万，低冲击<10bps）
        lines.append(f"  {i:>2}. {p['code']}: 涨{p['today_ret']}% gap{p['gap']}% 额{p['amount']}亿 仓≈{pos_1pct:.0f}万(1%ADV)")
    lines += [
        "",
        "【怎么执行】",
        "  gate=ON: 次日 14:57 收盘集合竞价限价买 top-20（T+1 close 买点避开盘高开，real-exec +0.389% > T+1 open +0.336%），持有到 T+5 收盘卖（4 天）",
        "  gate=OFF: 不交易，纸面跟踪（weight 0.3）",
        "  ⚠️ 真钱不进——等 60 天前向验证 + regime 转向（当前 OFF）",
        "  统计验证非已实现收益，cap ×0.3 是统计信心非保本，真钱仓位你手动定",
    ]
    text = "\n".join(lines)
    print(text)
    push_feishu(text)


if __name__ == "__main__":
    main()
