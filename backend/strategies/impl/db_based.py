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
        # 数据来源：seal_intraday_snapshots 分表最近交易日 open_count >= 2 的票
        # S089 C6：路由到当年最新月表（get_latest_partition → (db_path, table)），
        # 先查该月表 MAX(date)（最新交易日），再查 open_count >= 2 的票。
        # 数据缺失时空集，不命中任何票（诚实降级，不臆造候选）
        import sqlite3  # noqa: PLC0415
        from db_partition_router import get_latest_partition  # noqa: PLC0415

        zb_stocks: set[str] = set()
        try:
            latest = get_latest_partition()
            if latest is not None:
                zb_db, zb_table = latest
                zb_conn = sqlite3.connect(zb_db, timeout=5)
                try:
                    # 先取该月表最新交易日
                    row = zb_conn.execute(
                        f"SELECT MAX(date) FROM {zb_table}"
                    ).fetchone()
                    max_date = row[0] if row else None
                    if max_date:
                        zb_stocks = {r[0] for r in zb_conn.execute(
                            f"SELECT DISTINCT code FROM {zb_table} "
                            "WHERE open_count >= 2 AND date = ?",
                            (max_date,),
                        ).fetchall()}
                finally:
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
