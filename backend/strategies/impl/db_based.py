# -*- coding: utf-8 -*-
"""S086 B4：读私有数据库（seal_intraday.db）的战法（db_based）。

战法：reverse_package（炸板池 open_count>=2 的票包含 gene.code）。

match 条件/confidence 严格按 limitup_strategy.py:763-787 迁移，不改阈值。
依赖 sqlite3 + config.PRIVATE_DATA_DIR，与 gene_based 纯因子计算无关（避免循环依赖）。
数据缺失时空集，不命中任何票（诚实降级，不臆造候选）。
"""
from __future__ import annotations

from strategies.strategy_base import BaseStrategy, ConditionMatch


class ReversePackageStrategy(BaseStrategy):
    """反包战法：seal_intraday.db open_count>=2 的票包含 gene.code，confidence=固定 0.4。"""

    code = "reverse_package"
    name = "反包战法"

    def match(self, ctx) -> list[ConditionMatch]:
        # grill Q1-Q2：候选池从涨停池改为 S055 炸板池（open_count >= 2 = 反复开板的真炸板）
        # 数据来源：seal_intraday_snapshots 最近交易日 open_count >= 2 的票
        # 数据缺失时空集，不命中任何票（诚实降级，不臆造候选）
        import sqlite3  # noqa: PLC0415
        from config import PRIVATE_DATA_DIR  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        zb_db = str(Path(PRIVATE_DATA_DIR) / "seal_intraday.db")
        try:
            zb_conn = sqlite3.connect(zb_db, timeout=5)
            zb_stocks = {r[0] for r in zb_conn.execute(
                "SELECT DISTINCT code FROM seal_intraday_snapshots "
                "WHERE open_count >= 2 "
                "AND date = (SELECT MAX(date) FROM seal_intraday_snapshots)"
            ).fetchall()}
            zb_conn.close()
        except Exception:  # noqa: BLE001 - 数据缺失时空集，不命中任何票
            zb_stocks = set()

        if ctx.gene.code in zb_stocks:
            return [ConditionMatch(
                condition="前日炸板≥2次+今日反包",
                value="open_count >= 2（S055 炸板池）",
                description="策略逻辑上，该股前日反复开板（真炸板），今日反包概率较高",
            )]
        return []

    def compute_confidence(self, matches, ctx) -> float:
        return 0.4
