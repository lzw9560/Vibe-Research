# -*- coding: utf-8 -*-
"""S054 样本回填：假设用户按推荐建仓，合成 winrate 样本补全三桶数据。

口径（用户选定：快照推荐 + 合成 missed）：
- 读 gene_scores.db 历史日期（150 日），每只涨停股 70% 概率假设买入（funnel_candidate），
  30% 留作 missed 桶（不写 winrate_records，shadow-comparison 自动算 missed 收益）
- return_pct = _calc_next_day_return（信号日 close → 次日 close）
- entry_date = 信号日，exit_date = 次日（T+1 近似口径）
- 幂等：signal_ref='backfill:synthetic' 标记，重复跑前先删旧合成行

工程底线：只读 gene_scores.db + 本地 K 线缓存；零 em_get。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List

logger = logging.getLogger("vibe-research")

_SYNTH_REF = "backfill:synthetic"


def _list_gene_score_dates(limit: int = 60) -> List[str]:
    """gene_scores.db 已有日期降序（最多 limit 日）。"""
    try:
        from limitup_screener.data import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT date FROM gene_scores ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [r["date"] for r in rows]
    except Exception:
        return []


def _load_gene_scores_for_date(date: str) -> List[dict]:
    """读 gene_scores 指定日（code/name/total_score）。"""
    try:
        from limitup_screener.data import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT code, name, total_score FROM gene_scores WHERE date = ? ORDER BY total_score DESC",
            (date,),
        ).fetchall()
        conn.close()
        return [{"code": r["code"], "name": r["name"] or "", "gene_score": r["total_score"] or 0} for r in rows]
    except Exception:
        return []


def _calc_next_day_return(code: str, date_str: str) -> float | None:
    """次日收益率（复用 backtest_lite _meta，区分真 0% 与取数失败）。

    S123 R4：原用 float wrapper 把 fetch-failure 0.0 当 None 跳过→真 0% 收益
    被误排除→合成 winrate 样本失真（与 R4 win_rate.py 修法同原理，原 R4.5
    豁免错误）。改用 _meta：fetch_ok=False→None（取数失败跳过）；fetch_ok=True
    →真值（含 0.0=真 0%，纳入样本）。
    """
    try:
        from backtest_lite import _calc_next_day_return_meta as _calc_meta
        ret, fetch_ok = _calc_meta(code, date_str, {})
        return ret if fetch_ok else None
    except Exception:
        return None


def backfill_winrate_samples(days: int = 30) -> Dict[str, Any]:
    """回填合成样本。

    70% 假设买入（funnel_candidate），30% 留 missed。
    幂等：先删 signal_ref=_SYNTH_REF 旧行，再写新行。
    """
    from vr_paths import resolve_data_dir
    from win_rate_tracker import WinRateTracker, WinRateRecord

    gene_dates = _list_gene_score_dates(days)
    if not gene_dates:
        return {"backfilled": 0, "msg": "无 gene_scores 日期可回填"}

    tracker = WinRateTracker()
    db_path = tracker.db_path

    # 幂等：删旧合成行（表不存在则跳过——首次回填时 tracker 已建表）
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM winrate_records WHERE signal_ref = ?", (_SYNTH_REF,))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

    # 确定性伪随机：用 code+date 哈希决定 70/30 分配（不用 Math.random，保证幂等）
    def _is_bought(code: str, date: str) -> bool:
        h = hash(f"{code}|{date}") % 100
        return h < 70

    written = 0
    missed = 0
    failed = 0
    for d in gene_dates:
        scores = _load_gene_scores_for_date(d)

        for g in scores:
            code = g["code"]
            stock_name = g["name"] or code
            gene_score = g["gene_score"]

            ret = _calc_next_day_return(code, d)
            if ret is None:
                failed += 1
                continue

            if not _is_bought(code, d):
                missed += 1
                continue  # 留作 missed 桶（shadow-comparison 自动算）

            # 假设买入：entry=信号日 close, exit=次日 close
            entry_price = 10.0  # 占位，真实 close 需读 K 线
            exit_price = entry_price * (1 + ret)
            # 次日日期
            try:
                next_d = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            except Exception:
                next_d = d

            record = WinRateRecord(
                stock_code=code,
                stock_name=stock_name,
                strategy_used="涨停基因",
                entry_date=d,
                entry_price=entry_price,
                exit_date=next_d,
                exit_price=exit_price,
                return_pct=round(ret * 100, 2),
                is_win=ret > 0,
                gene_score=gene_score,
                sti_label="",
                sector="",
                signal_source="funnel_candidate",
                signal_ref=_SYNTH_REF,
                attention_mode="A",
            )
            try:
                tracker.add_record(record)
                written += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("[backfill_winrate] %s %s 写入失败: %s", d, code, exc)

    return {
        "backfilled": written,
        "missed_reserved": missed,
        "failed": failed,
        "snapshots": len(gene_dates),
        "msg": f"回填 {written} 笔假设买入，预留 {missed} 笔作 missed 桶，{failed} 笔 K 线缺失败",
    }
