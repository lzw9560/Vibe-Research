# -*- coding: utf-8 -*-
"""注册 combo_5d arm（S238）：is_active=1 weight_override=0.5（试探非重仓）。

combo-5d-edge 信号生成 + 60天前向 replay_check 都依赖 arm_status 行存在
（replay_check 用 UPDATE 非 UPSERT，须先建行）。本脚本 idempotent（UPSERT）。

weight 0.5 而非 1.0：combo spec 在 test 集迭代选出（test-set-selection 偏差），
t=11.94 乐观，真 OOS=60天前向 → 试探起步。详见 specs/S238-combo-5d-edge/spec.md §7.1。
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.trade_journal import TradeJournal  # noqa: E402


def main() -> None:
    tj = TradeJournal()  # _ensure_table 自动建表
    tj.set_arm_status("combo_5d", is_active=True, weight_override=0.5)
    st = tj.query_arm_status("combo_5d")
    print("✅ combo_5d arm 注册:", st)


if __name__ == "__main__":
    main()
