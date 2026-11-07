# -*- coding: utf-8 -*-
"""A股 regime 监控——combo-5d-edge 何时可启（2026-10-26；2026-10-27 接线前瞻跟踪）。

combo 是小盘动量 edge，regime-dependent：小盘熊段赔（10-21 批 -3% 印证）。
本脚本算当前 regime 信号，判 combo 何时可再启：

信号：
- breadth（>60日均线占比）：<30% 弱 / 30-50% 中 / >50% 强
- 小盘 decile0 5d/20d ret：负=小盘熊 / 正=小盘牛
- 小盘 vs 大盘 spread（decile0 - decile9 5d）：负=小盘领崩 / 正=小盘领涨
- combo 可启门：breadth > BREADTH_FLOOR AND 小盘 decile0 5d ret > SM5_FLOOR

⚠️ 阈值冻结（2026-10-27，前瞻验证前不可改）：
   BREADTH_FLOOR=0.4 / SM5_FLOOR=0.0 是 combo regime gate 的预注册阈值，前瞻验证
   30-60 天命中预测力前不可调（防 post-hoc 调阈值，§44 v3 R42-R44 教训）。
   命题A对抗已证伪"自动仓位开关"形态——本脚本只作诊断 + 前瞻跟踪，不接仓位。

用法：
  cd backend && .venv/bin/python tools/ashare_regime_monitor.py          # 打印当前 regime
  cd backend && .venv/bin/python tools/ashare_regime_monitor.py --log    # 打印 + 写 regime_gate_combo_log 表
"""

from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DB = resolve_data_dir() / "baostock_kline_cache.db"
LOG_DB = DB  # regime_gate_combo_log 表与 kline cache 同库

# ⚠️ FROZEN 2026-10-27——前瞻验证 30-60 天前不可改（§44 v3 R42-R44 防 post-hoc）
BREADTH_FLOOR = 0.4
SM5_FLOOR = 0.0


def main(args) -> None:
    conn = sqlite3.connect(str(DB), timeout=10)
    rows = conn.execute("SELECT code, bars_json FROM kline").fetchall()
    conn.close()
    last_dates: Counter = Counter()
    parsed = []
    for code, bj in rows:
        try:
            bars = json.loads(bj)
        except Exception:
            continue
        if len(bars) < 70:
            continue
        d = bars[-1].get("date", "")
        if d:
            last_dates[d] += 1
        parsed.append((code, bars))
    if not last_dates:
        print("cache 空（refresh 未跑或失败）")
        return
    modal = last_dates.most_common(1)[0][0]

    above60 = 0
    total = 0
    small_5d = []  # decile0-1 (最小 20%)
    small_20d = []
    large_5d = []  # decile8-9 (最大 20%)
    caps = []
    for code, bars in parsed:
        idx = None
        for i in range(len(bars) - 1, -1, -1):
            bd = bars[i].get("date", "")
            if bd == modal:
                idx = i
                break
            if bd < modal:
                break
        if idx is None or idx < 60:
            continue
        c = float(bars[idx].get("close", 0) or 0)
        vol = float(bars[idx].get("volume", 0) or 0)
        turn = float(bars[idx].get("turn", 0) or 0)
        if not c or not vol or not turn:
            continue
        ma60 = statistics.mean(float(bars[j].get("close", 0) or 0) for j in range(idx - 60, idx))
        if not ma60 or idx - 20 < 0:
            continue
        prev5 = float(bars[idx - 5].get("close", 0) or 0) if idx - 5 >= 0 else 0
        prev20 = float(bars[idx - 20].get("close", 0) or 0) if idx - 20 >= 0 else 0
        if not prev5 or not prev20:
            continue
        ret5 = (c - prev5) / prev5
        ret20 = (c - prev20) / prev20
        cap = (vol / (turn / 100)) * c / 1e8
        above60 += 1 if c > ma60 else 0
        total += 1
        caps.append((cap, ret5, ret20))

    breadth = above60 / total if total else 0
    caps.sort()
    n = len(caps)
    small = caps[: n // 5]  # decile0-1
    large = caps[4 * n // 5 :]  # decile8-9
    sm5 = statistics.mean(r for _, r, _ in small) if small else 0
    sm20 = statistics.mean(r20 for _, _, r20 in small) if small else 0
    lg5 = statistics.mean(r for _, r, _ in large) if large else 0
    spread = sm5 - lg5

    print(f"=== A股 regime 监控（as of {modal}）===")
    print(f"breadth (>60MA): {breadth * 100:.1f}%  {'弱(<30)' if breadth < 0.3 else '中(30-50)' if breadth < 0.5 else '强(>50)'}")
    print(f"小盘 decile0-1 5d: {sm5 * 100:+.2f}%  20d: {sm20 * 100:+.2f}%  {'熊(负)' if sm5 < 0 else '牛(正)'}")
    print(f"大盘 decile8-9 5d: {lg5 * 100:+.2f}%")
    print(f"小盘-大盘 spread 5d: {spread * 100:+.2f}%  {'小盘领崩' if spread < 0 else '小盘领涨'}")
    print()
    # combo 可启门：FROZEN 阈值（breadth > BREADTH_FLOOR AND 小盘 5d > SM5_FLOOR）
    viable = breadth > BREADTH_FLOOR and sm5 > SM5_FLOOR
    not_viable_reason = ("小盘未止跌" if sm5 <= SM5_FLOOR else "") + ("广度未回升" if breadth <= BREADTH_FLOOR else "")
    action = "✅ 可启" if viable else f"❌ 不可启——{not_viable_reason}"
    print(f"combo 可启门（breadth>{BREADTH_FLOOR * 100:.0f}% AND 小盘5d>{SM5_FLOOR * 100:.0f}%）: {action}")
    if not viable:
        print("  → combo 暂停（regime 不匹配小盘动量），等小盘止跌+breadth 回升再启")

    if args.log:
        _log_gate(modal, breadth, sm5, sm20, lg5, spread, viable, action)


def _log_gate(date, breadth, sm5, sm20, lg5, spread, viable, action) -> None:
    """写 regime_gate_combo_log 表（前瞻跟踪——30-60 天后对比 combo 实际结果验 gate 预测力）。

    命题A对抗证伪了"自动仓位开关"形态，但 surviving kernel = "regime 从未被市场状态
    检验过"。本表记每日 gate 预测（viable or not），30-60 天后对比 combo 纸面 settle
    结果，回答 gate 有无前向预测力（命题B的前置）。
    """
    conn = sqlite3.connect(str(LOG_DB), timeout=10)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS regime_gate_combo_log ("
            "date TEXT PRIMARY KEY, breadth REAL, sm5 REAL, sm20 REAL, "
            "lg5 REAL, spread REAL, viable INTEGER, combo_action TEXT, logged_at TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO regime_gate_combo_log (date, breadth, sm5, sm20, lg5, spread, viable, combo_action, logged_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (date, breadth, sm5, sm20, lg5, spread, 1 if viable else 0, action, datetime.datetime.now().isoformat()),
        )
        conn.commit()
        print(f"[log] regime_gate_combo_log 写入 date={date} viable={1 if viable else 0}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A股 regime 监控（combo-5d-edge gate，FROZEN 阈值）")
    parser.add_argument("--log", action="store_true", help="写 regime_gate_combo_log 表（前瞻跟踪）")
    args = parser.parse_args()
    main(args)
