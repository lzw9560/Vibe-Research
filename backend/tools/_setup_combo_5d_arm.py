# -*- coding: utf-8 -*-
"""注册 combo_5d arm（S238）：is_active=1 weight_override=0.0（风险止血，paper tracking 保留）。

combo-5d-edge 信号生成 + 60天前向 replay_check 都依赖 arm_status 行存在
（replay_check 用 UPDATE 非 UPSERT，须先建行）。本脚本 idempotent（UPSERT）。

weight_override=0.0（2026-11-08）：combo edge 经 9 专家 panel 10 角度证伪为可交易 alpha
（real-exec Bartlett NW t_nw=1.487 FAIL / permutation p=0.47 / OLS alpha t=0.82 /
 live -3.649% 101 picks / Kelly 负）。详见 memory [[combo-edge-falsified-expert-panel-2026-11-08]]。
is_active=True 保留——60 天前向继续累积（确认 falsified 非复活，不上真钱）。
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.trade_journal import TradeJournal  # noqa: E402


def main() -> None:
    tj = TradeJournal()  # _ensure_table 自动建表
    tj.set_arm_status("combo_5d", is_active=True, weight_override=0.0)  # 2026-11-08 combo FALSIFIED，零权重止血，paper tracking 保留
    st = tj.query_arm_status("combo_5d")
    print("✅ combo_5d arm 注册:", st)


if __name__ == "__main__":
    main()
