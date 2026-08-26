# -*- coding: utf-8 -*-
"""S086 B4：读私有数据库（seal_intraday.db）的战法（db_based）。

战法：reverse_package（炸板池 open_count>=2 的票包含 gene.code）。

match 条件/confidence 严格按 limitup_strategy.py:763-787 迁移，不改阈值。
依赖 sqlite3 + config.PRIVATE_DATA_DIR，与 gene_based 纯因子计算无关（避免循环依赖）。
数据缺失时空集，不命中任何票（诚实降级，不臆造候选）。
"""
from __future__ import annotations

from strategies.strategy_base import (
    BaseStrategy, ConditionMatch, ConditionEval, StrategyMatchResult, make_data_unavailable_result,
)


def _get_pattern(ctx):
    """S094 R4 辅助：从 ctx.market_scan_ctx 取 PatternScan（S1 阶段涨停 pipeline 无此字段，None 降级）。"""
    msc = getattr(ctx, "market_scan_ctx", None)
    if not msc:
        return None
    return msc.get("pattern") if isinstance(msc, dict) else None


class ReversePackageStrategy(BaseStrategy):
    """反包战法：seal_intraday.db open_count>=2 的票包含 gene.code，confidence=固定 0.4。"""

    code = "reverse_package"
    name = "反包战法"

    def match(self, ctx) -> StrategyMatchResult:
        # S097：C1 前日真炸板（open_count>=2 池含 code）；DB 缺/异常 → data_ok=False 整战法降级
        # grill Q1-Q2：候选池从涨停池改为 S055 炸板池（open_count >= 2 = 反复开板的真炸板）
        # S089 C6：路由到当年最新月表（get_latest_partition → (db_path, table)），
        # 先查该月表 MAX(date)（最新交易日），再查 open_count >= 2 的票。
        import sqlite3  # noqa: PLC0415
        from db_partition_router import get_latest_partition  # noqa: PLC0415

        zb_stocks: set[str] = set()
        db_ok = True
        try:
            latest = get_latest_partition()
            if latest is None:
                db_ok = False
            else:
                zb_db, zb_table = latest
                zb_conn = sqlite3.connect(zb_db, timeout=5)
                try:
                    # 先取该月表最新交易日
                    row = zb_conn.execute(
                        f"SELECT MAX(date) FROM {zb_table}"
                    ).fetchone()
                    max_date = row[0] if row else None
                    if not max_date:
                        db_ok = False
                    else:
                        zb_stocks = {r[0] for r in zb_conn.execute(
                            f"SELECT DISTINCT code FROM {zb_table} "
                            "WHERE open_count >= 2 AND date = ?",
                            (max_date,),
                        ).fetchall()}
                finally:
                    zb_conn.close()
        except Exception:  # noqa: BLE001 - 数据缺失降级
            db_ok = False

        if not db_ok:
            return make_data_unavailable_result(self.code, self.name, [
                ("reverse_package.c1", "前日真炸板", "open_count", ">= 2"),
            ])

        hit = ctx.gene.code in zb_stocks
        conditions = [ConditionEval(
            condition_id="reverse_package.c1", condition_name="前日真炸板",
            factor="open_count", threshold=">= 2",
            actual_value="命中炸板池" if hit else "不在炸板池",
            state="hit" if hit else "miss",
            description=("前日反复开板（真炸板 open_count>=2），今日反包概率较高" if hit
                         else "前日未在炸板池（open_count<2），非反包候选"),
        )]
        hit_count = 1 if hit else 0
        return StrategyMatchResult(
            strategy_code=self.code, strategy_name=self.name, conditions=conditions,
            hit_count=hit_count, total_count=1, fired=hit,
            fire_rule="全条件命中",
            confidence=0.4 if hit else None, data_ok=True,
        )

    def compute_confidence(self, matches, ctx) -> float:
        return 0.4

    def compute_volume_signal(self, ctx) -> bool | None:
        """S094 R4：反包成交额 > 15亿（spec §3.R4）。"""
        pattern = _get_pattern(ctx)
        if pattern is None or pattern.amount_yi is None:
            return None
        return pattern.amount_yi > 15
