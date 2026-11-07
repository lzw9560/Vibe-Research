# -*- coding: utf-8 -*-
"""修 trade_journal 里 inst_dominant 10-09 top6 的假数据（2026-10-18）。

问题：6 条 signal 的 entry_price=10-09 open 占位（146.88 等，note "实际成交价待用户补"），
unrealized_pnl=10-09 晚 pre-entry 投影快照（mean +1.857% 假数），is_realized=0 但 exit 未记。
replay_check 读 unrealized → 报 phantom +1.857%，非真实 -7.49%。

修法（mechanical strategy price，与回测 apples-to-apples）：
- entry_price → 10-12 open（T+1 open，spec 口径，用户还在持有）
- unrealized_pnl → (10-16 close - 10-12 open) / 10-12 open * 100（到上一交易日收盘的真实浮亏）
- is_realized 保持 0（用户还在持有，10-23 计划卖）
- exit_price/exit_date/net_pnl 保持 None
- fills_json 追记 mechanical 标注 + 用户实际 fill 仍待补

用户实际成交价若与 10-12 open 不同（滑点/部分成交），用户可再 override。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import baostock as bs

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vr_paths import resolve_data_dir


DATA = resolve_data_dir()
DB = DATA / "trade_journal.db"

TOP6 = {
    "002384": "sz.002384",
    "688313": "sh.688313",
    "300684": "sz.300684",
    "600330": "sh.600330",
    "002614": "sz.002614",
    "000513": "sz.000513",
}
ENTRY_DATE = "2026-10-12"  # T+1 open（周一）
CURR_DATE = "2026-10-16"  # 上一交易日收盘（周五），用户还在持有


def fetch_entry_curr(code: str) -> tuple[float | None, float | None]:
    """baostock 取 ENTRY_DATE open + CURR_DATE close（前复权）。"""
    rs = bs.query_history_k_data_plus(
        code, "date,open,close", start_date=ENTRY_DATE, end_date=CURR_DATE,
        frequency="d", adjustflag="2",
    )
    bars = {}
    while rs.error_code == "0" and rs.next():
        d, o, c = rs.get_row_data()
        bars[d] = (float(o) if o else None, float(c) if c else None)
    entry = bars.get(ENTRY_DATE, (None, None))[0]
    curr = bars.get(CURR_DATE, (None, None))[1]
    return entry, curr


def main() -> None:
    # backup
    backup = DB.with_suffix(".db.bak-2026-10-18")
    backup.write_bytes(DB.read_bytes())
    print(f"backup: {backup}")

    bs.login()
    print(f"\n{'code':<8}{'10-12open':>12}{'10-16close':>12}{'unreal%':>10}")
    print("-" * 44)
    updates = []
    for sc, bc in TOP6.items():
        entry, curr = fetch_entry_curr(bc)
        if entry is None or curr is None:
            print(f"{sc:<8}  SKIP (data missing)")
            continue
        unreal = round((curr - entry) / entry * 100, 3)
        print(f"{sc:<8}{entry:>12.2f}{curr:>12.2f}{unreal:>+9.3f}%")
        sid = f"inst_dominant_2026-10-09_{sc}"
        fills = [
            {"date": "2026-10-12", "price": entry, "side": "buy",
             "note": "T+1 open 机械策略价（spec 口径）；用户实际成交价待补"},
        ]
        updates.append((entry, unreal, json.dumps(fills, ensure_ascii=False), sid))
    bs.logout()

    conn = sqlite3.connect(str(DB))
    for entry, unreal, fills, sid in updates:
        conn.execute(
            "UPDATE trade_journal SET entry_price=?, unrealized_pnl=?, fills_json=? "
            "WHERE signal_id=?",
            (entry, unreal, fills, sid),
        )
    conn.commit()
    print(f"\nupdated {len(updates)} records (entry_price + unrealized_pnl + fills_json)")
    print("is_realized/exit_price/exit_date/net_pnl 保持原样（用户还在持有）")

    # 验证：replay_check 应报真实 mean
    rows = conn.execute(
        "SELECT stock_code, entry_price, unrealized_pnl, is_realized "
        "FROM trade_journal WHERE arm='inst_dominant' ORDER BY signal_id"
    ).fetchall()
    print("\n=== 验证 ===")
    print(f"{'code':<8}{'entry':>10}{'unreal':>10}{'realized':>9}")
    for c, e, u, r in rows:
        print(f"{c:<8}{e:>10.2f}{u:>+9.3f}%{'Y' if r else 'N':>9}")
    reals = [u for _, _, u, _ in rows if u is not None]
    if reals:
        print(f"\nreplay_check mean 将报: {sum(reals)/len(reals):+.4f}% (vs 之前 phantom +1.857%)")
    conn.close()


if __name__ == "__main__":
    main()
