# -*- coding: utf-8 -*-
"""R12 size-matched 预检——inst_dominant 的 size decile 分布。

inst_dominant walk-forward OOS edge-confirmed（train+0.426%/test+0.345% 都 PASS）。
但须 R12 size-matched 排除 size premium（playbook 59% 部分是 size 的教训，S2 微盘 91% 是 size）。

本脚本（预检）：算 inst_dominant picks 的 20d 均成交额分布。
  - 偏小盘（decile 1-3 占比>40%）→ size premium 风险大，须完整 size-matched BHAR
  - 分散 → size premium 风险小
完整 R12 BHAR（vs 全市场同 decile peers）下一步。
"""

import json
import sqlite3
from pathlib import Path
from collections import defaultdict

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DT_DB = DATA / "dragon_tiger_history.db"
KLINE_DB = DATA / "baostock_kline_cache.db"

INST_KEYWORDS = (
    "机构专用",
    "总部",
    "高盛",
    "瑞银",
    "股通",
    "摩根",
    "中信证券股份有限公司上海分公司",
    "国际金融",
)


def load_inst_dominant() -> list:
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute("SELECT trade_date, security_code, dept_name, buy, net FROM dragon_tiger_rows WHERE side='buy' AND buy > 0").fetchall()
    conn.close()
    picks_by_dc: dict = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks_by_dc[(date, code)].append((dept or "", buy or 0, net or 0))
    inst: list = []
    for (date, code), seats in picks_by_dc.items():
        total = sum(s[1] for s in seats)
        if total <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        if inst_buy / total > 0.5:
            inst.append((date, code))
    return inst


_KLINE_CACHE: dict = {}


def get_20d_avg_amt(code: str, trade_date: str) -> float | None:
    """个股 trade_date 前 20 交易日均成交额（size 代理，同 explore_factor_size）。"""
    if code not in _KLINE_CACHE:
        conn = sqlite3.connect(str(KLINE_DB))
        row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code,)).fetchone()
        conn.close()
        if not row:
            _KLINE_CACHE[code] = []
        else:
            try:
                _KLINE_CACHE[code] = sorted(json.loads(row[0]), key=lambda b: b.get("date", ""))
            except Exception:
                _KLINE_CACHE[code] = []
    bars = _KLINE_CACHE[code]
    before = [b for b in bars if b.get("date", "") <= trade_date][-20:]
    if len(before) < 10:
        return None
    return sum(b.get("amount", 0) or 0 for b in before) / len(before)


def audit_size_decile() -> None:
    inst = load_inst_dominant()
    print(f"=== inst_dominant size decile 分布（R12 预检）===")
    print(f"总 picks: {len(inst)}\n")

    amts: list = []
    for date, code in inst:
        a = get_20d_avg_amt(code, date)
        if a is not None:
            amts.append((date, code, a))

    if not amts:
        print("无成交额数据")
        return

    # inst_dominant 自身分布分 10 decile（预检，非全市场基准）
    sorted_amts = sorted(a[2] for a in amts)
    n = len(sorted_amts)
    deciles = [sorted_amts[min(n - 1, n * i // 10)] for i in range(11)]

    print(f"成交额分布（亿，inst_dominant 自身）:")
    for i in range(10):
        lo, hi = deciles[i] / 1e8, deciles[i + 1] / 1e8
        cnt = sum(1 for a in amts if deciles[i] <= a[2] < deciles[i + 1])
        print(f"  decile {i + 1}: {lo:.2f}~{hi:.2f}亿 ({cnt} picks)")

    # 全市场成交额中位数（粗基准）——用 dragon_tiger 所有上榜股的 20d 均成交额
    print(f"\n注：完整 R12 须 vs 全市场同 decile peers BHAR（本脚本仅预检 inst_dominant 自身分布）")

    # 偏小盘判定（decile 1-3 占比 = 30% 基线）
    small_threshold = deciles[3]
    small_cnt = sum(1 for a in amts if a[2] < small_threshold)
    print(f"\n小盘（decile 1-3, <{small_threshold / 1e8:.2f}亿）: {small_cnt}/{n} = {small_cnt / n * 100:.1f}%")
    print(f"  → {'偏小盘，size premium 风险大，须完整 size-matched BHAR' if small_cnt / n > 0.35 else '分散，size premium 风险小（但仍须完整 BHAR 确认）'}")


if __name__ == "__main__":
    audit_size_decile()
