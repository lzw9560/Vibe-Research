# -*- coding: utf-8 -*-
"""记录当日 combo_5d picks 到 trade_journal（paper 跟踪，pending）。

60天前向 §44 R3 replay_check 依赖：每日 signal picks 入库（entry_price/exit 待 settle 填）。
Paper 跟踪 = 记录信号表现，独立于用户是否真交易（验证信号 edge，非用户执行）。
Idempotent：signal_id = combo_5d_{signal_date}_{code}，INSERT OR REPLACE 覆盖重跑。

用法：cd backend && .venv/bin/python tools/combo_5d_daily_record.py [--date YYYY-MM-DD]
"""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "tools"))
sys.path.insert(0, str(ROOT / "backend"))

from commander_runner import load_combo_5d_today  # noqa: E402
from engine.trade_journal import TradeJournal, JournalRecord  # noqa: E402


def record_combo_5d(date: str | None = None) -> int:
    """记录 combo_5d picks 为 pending paper entries（entry_price=None）。返记录数。"""
    picks = load_combo_5d_today(date=date) if date else load_combo_5d_today()
    if not picks:
        print("[record] 无 picks（cache stale 或 universe 不足）")
        return 0
    signal_date = picks[0]["date"]
    tj = TradeJournal()
    n = 0
    for p in picks:
        rec = JournalRecord.create(
            arm="combo_5d",
            stock_code=p["code"],
            entry_price=None,  # pending，settle 时填 T+1 open
            entry_date=signal_date,  # 信号日（settle 用此定位 bar idx）
            exit_model_version="nostop_t5",
        )
        tj.insert(rec)  # INSERT OR REPLACE 幂等
        n += 1
    print(f"[record] {signal_date} 记录 {n} picks（arm=combo_5d，pending，T+1 open + T+5 exit 待 settle）")
    return n


if __name__ == "__main__":
    d = None
    if "--date" in sys.argv:
        i = sys.argv.index("--date")
        d = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    record_combo_5d(d)
