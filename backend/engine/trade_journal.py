# -*- coding: utf-8 -*-
"""S173 Trade Journal 闭环 ledger——跨臂胜率全链路 SQLite 账本。

**与 journal.py(S166) 分离**（spec §5.1）：journal.py 是用户手动真实成交账本
（trades.json + fees.json），本模块是模拟/纸面臂自动录（orchestrator 批量调
signal 生成器 → executor → accounting → 写 SQLite）。口径不同不混录：
真实成交走 journal.py → settlement_recorder → winrate.db；
模拟闭环走 trade_journal.py（accounting path_return apply_cost=True 净口径）。

**C7 隔离**：journal_recorder 是闭环臂唯一写入者，winrate.db legacy 只读。
两库独立：trade_journal（模拟闭环）+ winrate.db（手动真实成交）。

**统计方法论层**（H1/H2）：复用 s44_verifier 不重发明——
  - 净超额：day_clustered_t_test（防同日 picks 膨胀 n）
  - 4 臂多重检验：bonferroni_bh（K cap 8）
  - Sharpe：日聚合 + compute_dsr（DSR+MinTRL）
  - haircut：compute_haircut
  - 胜率 CI：Wilson score interval
  - underpowered gate：n<30 或 days<60 → status='underpowered' 不出 kill

聚合走 SQLite query 不读结果 cache（memory s088 重算范式）。
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from vr_paths import resolve_data_dir

# s44_verifier 统计函数（复用不重发明）
from s44_verifier.stats import day_clustered_t_test, bonferroni_bh
from s44_verifier.wiring import compute_dsr, compute_haircut


#: pnl 单位固定 CNY（H3 统一）。
PNL_UNIT_CNY: str = "CNY"

#: underpowered gate 阈值（H1/H4）
MIN_PICKS_FOR_KILL: int = 30
MIN_DAYS_FOR_KILL: int = 60

#: 4 臂多重检验 K cap（§44v2）
MAX_BONFERRONI_K: int = 8

#: 初始资本默认值（drawdown 百分比分母）
DEFAULT_INITIAL_CAPITAL: float = 100000.0

#: S175 T9 — 各臂 §44 verdict 静态标签（诚实呈现，grill C7：falsified ≠ weak ≠ 待复验）
#: externally_validated=外部文献验证（非本系统 §44）；§44_falsified=S168 证否；dead_arm=§44 成本假象 falsified
ARM_VERDICT: dict[str, str] = {
    "floor": "externally_validated",   # 红利低波 9-12% 三重定论（学术+卖方+指数），非本系统 §44
    "breakout": "§44_falsified",        # S168 12 harness 全 falsified，selection 无 edge
    "gap": "dead_arm",                   # §44 falsified 成本假象 net -0.48% t=-3.79
    "limitup": "mock_not_ready",         # signal 生成器未建，mock_entry=10.0
    "trend": "exploratory",             # S181 已升级实臂（trend_swing_arm 真 generator），§44 未验
}
#: dormant 臂（不跑生产/mock 未就绪，无记录）——aggregate 显式加 stub 让 UI 显诚实标签。
#: gap 不在此（gap 有 is_dead_arm=1 记录，走 RecordRow dead badge，不进 aggregate 防污染存活臂统计）
#: trend S181 已升级实臂移出 dormant（仍 0 signals 但真 generator 非 mock）
DORMANT_ARMS: tuple[str, ...] = ("limitup",)


@dataclass(frozen=True)
class JournalRecord:
    """闭环交易记录（immutable，spec §5.2 schema）。

    signal_id: UUID，跨臂唯一（journal_recorder 生成，C8——不灌 Trades dataclass）。
    arm: 'floor'|'breakout'|'limitup'|'trend'|'gap'（string tag，前向兼容）。
    net_pnl: CNY（H3），走 accounting.path_return/gap_net_return(apply_cost=True) 折算。
    is_realized: 0=unrealized 持仓（每日 MTM 更新） 1=已平仓。
    is_dead_arm: gap 等 falsified 臂标 1，不参与聚合胜率但保留录（可复盘）。
    """

    signal_id: str
    arm: str
    stock_code: str
    entry_price: float | None
    entry_date: str
    exit_price: float | None = None
    exit_date: str | None = None
    exit_reason: str | None = None
    net_pnl: float | None = None
    pnl_unit: str = PNL_UNIT_CNY
    cost_pct: float = 0.0
    gross_return: float | None = None
    is_realized: int = 0
    unrealized_pnl: float | None = None
    is_dead_arm: int = 0
    fills_json: str = ""
    created_at: str = ""
    # S201b stage 2: 版本保留——新 exit model 的 gross 写 v2，冻结 gross_return 不动
    gross_return_v2: float | None = None
    exit_model_version: str = ""

    @classmethod
    def create(
        cls, arm: str, stock_code: str, entry_price: float | None,
        entry_date: str, **kwargs: Any,
    ) -> "JournalRecord":
        """构造新记录，signal_id 确定性（arm_entry_date_stock_code）+ created_at。

        S183 审查发现：原 UUID signal_id 导致 _process_* 重跑累积重复（000798/09-08 有 3 条）。
        改确定性 id 让 INSERT OR REPLACE 覆盖（重跑幂等）。signal_id 可 kwargs 覆盖
        （settle 用 pos.signal_id 覆盖旧 id；测试可传 mock id）。
        """
        now = datetime.now().isoformat()
        signal_id = kwargs.pop("signal_id", None) or f"{arm}_{entry_date}_{stock_code}"
        return cls(
            signal_id=signal_id,
            arm=arm,
            stock_code=stock_code,
            entry_price=entry_price,
            entry_date=entry_date,
            created_at=kwargs.pop("created_at", now),
            **kwargs,
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_journal (
  signal_id       TEXT PRIMARY KEY,
  arm             TEXT NOT NULL,
  stock_code      TEXT NOT NULL,
  entry_price     REAL,
  entry_date      TEXT NOT NULL,
  exit_price      REAL,
  exit_date       TEXT,
  exit_reason     TEXT,
  net_pnl         REAL,
  pnl_unit        TEXT DEFAULT 'CNY',
  cost_pct        REAL,
  gross_return    REAL,
  is_realized     INTEGER DEFAULT 0,
  unrealized_pnl  REAL,
  is_dead_arm     INTEGER DEFAULT 0,
  fills_json      TEXT,
  created_at      TEXT NOT NULL,
  gross_return_v2 REAL,
  exit_model_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_tj_arm ON trade_journal(arm);
CREATE INDEX IF NOT EXISTS idx_tj_entry_date ON trade_journal(entry_date);
CREATE INDEX IF NOT EXISTS idx_tj_is_realized ON trade_journal(is_realized);
"""


class TradeJournal:
    """闭环 ledger（SQLite CRUD + 跨臂聚合 + 统计方法论）。

    存 `.vibe-research/trade_journal.db`（vr_paths.resolve_data_dir()，gitignored）。
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or (resolve_data_dir() / "trade_journal.db")
        self._ensure_table()

    def _ensure_table(self) -> None:
        """迁移幂等（memory migration-stubs-fresh-db-fix：v1 完整 CREATE 不做桩）。"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript(_SCHEMA)
            # S201b stage 2: 版本保留列（additive ALTER TABLE，幂等）
            cols = {row[1] for row in conn.execute("PRAGMA table_info(trade_journal)")}
            if "gross_return_v2" not in cols:
                conn.execute("ALTER TABLE trade_journal ADD COLUMN gross_return_v2 REAL")
            if "exit_model_version" not in cols:
                conn.execute("ALTER TABLE trade_journal ADD COLUMN exit_model_version TEXT")
            conn.commit()
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── CRUD ──────────────────────────────────────────────────────────

    def insert(self, record: JournalRecord) -> str:
        """插入一条闭环交易记录。返 signal_id。INSERT OR REPLACE 幂等。"""
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO trade_journal
                   (signal_id, arm, stock_code, entry_price, entry_date,
                    exit_price, exit_date, exit_reason, net_pnl, pnl_unit,
                    cost_pct, gross_return, is_realized, unrealized_pnl,
                    is_dead_arm, fills_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record.signal_id, record.arm, record.stock_code,
                 record.entry_price, record.entry_date,
                 record.exit_price, record.exit_date, record.exit_reason,
                 record.net_pnl, record.pnl_unit, record.cost_pct,
                 record.gross_return, record.is_realized,
                 record.unrealized_pnl, record.is_dead_arm,
                 record.fills_json, record.created_at),
            )
            conn.commit()
        finally:
            conn.close()
        return record.signal_id

    def update_unrealized(
        self, signal_id: str, unrealized_pnl: float, current_price: float,
    ) -> bool:
        """更新 floor 臂持仓的 unrealized_pnl（C6 每日盘后 MTM）。"""
        conn = self._conn()
        try:
            cur = conn.execute(
                """UPDATE trade_journal SET unrealized_pnl=?, exit_price=?
                   WHERE signal_id=? AND is_realized=0""",
                (unrealized_pnl, current_price, signal_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def update_settlement_v2(
        self, signal_id: str, gross_return_v2: float, exit_price: float,
        exit_date: str, exit_reason: str, net_pnl: float, cost_pct: float,
        exit_model_version: str = "v2_gap_through_aware",
    ) -> bool:
        """S201b stage 2 — UPDATE 结算字段 + v2 列，冻结 gross_return 不动。

        **绝不 INSERT OR REPLACE**（spec verdict #6：覆盖全字段无 before-image，
        违 reproducibility 底线）。此方法只 UPDATE 指定字段，保留 gross_return
        + fills_json + created_at 不变。只碰 is_realized=0 holds（set → 1）。
        """
        conn = self._conn()
        try:
            cur = conn.execute(
                """UPDATE trade_journal
                   SET gross_return_v2=?, exit_price=?, exit_date=?, exit_reason=?,
                       net_pnl=?, cost_pct=?, is_realized=1, exit_model_version=?
                   WHERE signal_id=? AND is_realized=0""",
                (gross_return_v2, exit_price, exit_date, exit_reason,
                 net_pnl, cost_pct, exit_model_version, signal_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def query_records(
        self, arm: str | None = None, is_realized: int | None = None,
        is_dead_arm: int | None = 0, limit: int = 5000,
    ) -> list[JournalRecord]:
        """查询记录。is_dead_arm 默认 0（只查存活臂），传 None 查全部。"""
        clauses: list[str] = []
        params: list[Any] = []
        if arm is not None:
            clauses.append("arm=?")
            params.append(arm)
        if is_realized is not None:
            clauses.append("is_realized=?")
            params.append(is_realized)
        if is_dead_arm is not None:
            clauses.append("is_dead_arm=?")
            params.append(is_dead_arm)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        conn = self._conn()
        try:
            rows = conn.execute(
                f"SELECT * FROM trade_journal {where} ORDER BY entry_date DESC LIMIT ?",
                params,
            ).fetchall()
        finally:
            conn.close()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> JournalRecord:
        # S201b stage 2: gross_return_v2/exit_model_version 可能不存在于旧 DB（migration 前）
        gr_v2 = row["gross_return_v2"] if "gross_return_v2" in row.keys() else None
        emv = row["exit_model_version"] if "exit_model_version" in row.keys() else ""
        return JournalRecord(
            signal_id=row["signal_id"], arm=row["arm"],
            stock_code=row["stock_code"], entry_price=row["entry_price"],
            entry_date=row["entry_date"], exit_price=row["exit_price"],
            exit_date=row["exit_date"], exit_reason=row["exit_reason"],
            net_pnl=row["net_pnl"], pnl_unit=row["pnl_unit"],
            cost_pct=row["cost_pct"], gross_return=row["gross_return"],
            is_realized=row["is_realized"],
            unrealized_pnl=row["unrealized_pnl"],
            is_dead_arm=row["is_dead_arm"],
            fills_json=row["fills_json"] or "",
            created_at=row["created_at"],
            gross_return_v2=gr_v2,
            exit_model_version=emv or "",
        )

    # ── equity 曲线（C4/C6）────────────────────────────────────────────

    def equity_curve(
        self, arm: str | None = None,
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    ) -> list[dict]:
        """equity 曲线 = initial_capital + cumulative(realized + unrealized MTM)。

        遵循 risk_rules.equity_curve 绝对 CNY 回撤模式（C4）：
        drawdown_cny = peak_cny - current_cny（非零基百分比 (peak-current)/peak）。
        """
        records = self.query_records(arm=arm, is_dead_arm=None)
        if not records:
            return [{"date": "", "equity": initial_capital,
                     "cum_pnl": 0.0, "drawdown_cny": 0.0}]

        # 按平仓日/持仓日排序
        dated: list[tuple[str, float]] = []
        for r in records:
            pnl = 0.0
            if r.is_realized and r.net_pnl is not None:
                pnl = float(r.net_pnl)
            elif r.unrealized_pnl is not None:
                pnl = float(r.unrealized_pnl)
            date = r.exit_date or r.entry_date
            dated.append((date, pnl))

        dated.sort(key=lambda x: x[0])
        points: list[dict] = []
        cum = 0.0
        peak = 0.0
        for date, pnl in dated:
            cum += pnl
            equity = initial_capital + cum
            peak = max(peak, cum)
            dd_cny = peak - cum
            points.append({
                "date": date, "equity": round(equity, 2),
                "cum_pnl": round(cum, 2),
                "drawdown_cny": round(dd_cny, 2),
            })
        return points

    # ── 跨臂聚合 + 统计方法论（H1/H2/H8）──────────────────────────────

    def aggregate_by_arm(self, arm: str | None = None) -> dict:
        """跨臂聚合统计。SQLite query 不读结果 cache（memory s088 重算范式）。

        per-arm: net_winrate (Wilson CI) / Sharpe (日聚合+DSR+MinTRL) /
        净超额 (day_clustered_t_test+CI) / 盈亏比 / 总 net_pnl /
        signal_coverage_rate / execution_winrate（H8 三指标）。
        is_dead_arm=1 不混入（防 falsified 臂污染存活臂统计）。
        n<30 或 days<60 → status='underpowered' 不出 kill（H1/H4）。
        """
        arms = [arm] if arm else self._distinct_arms()
        result: dict[str, Any] = {}
        p_values: list[float] = []

        for a in arms:
            records = self.query_records(arm=a, is_realized=1, is_dead_arm=0)
            stats = _compute_arm_stats(records)
            stats["s44_verdict"] = ARM_VERDICT.get(a, "untested")  # S175 T9 诚实标签
            result[a] = stats
            if stats.get("p_one_sided") is not None:
                p_values.append(stats["p_one_sided"])

        # S175 T9：dormant 臂 stub（不跑生产/已证否/mock）——显式加让 UI 显诚实标签
        for a in DORMANT_ARMS:
            if a not in result:
                stats = _compute_arm_stats([])
                stats["s44_verdict"] = ARM_VERDICT.get(a, "untested")
                stats["dormant"] = True
                stats["dormant_note"] = "dormant—未跑生产/已证否/mock，结构在等插槽"
                result[a] = stats

        # 4 臂多重检验（H1：bonferroni_bh，K cap 8）
        if len(p_values) > 1:
            adjusted = bonferroni_bh(
                p_values, n=min(len(p_values), MAX_BONFERRONI_K),
                method="BH",
            )
            arms_with_p = [a for a in arms if result[a].get("p_one_sided") is not None]
            for i, a in enumerate(arms_with_p):
                result[a]["p_adjusted_bh"] = adjusted[i] if i < len(adjusted) else None

        return result

    def query_winrate_trends(self, arm: str | None = None) -> list[dict]:
        """S183：累积胜率时序（按周分桶，实时聚合非落盘 snapshot）。

        查 is_realized=1 AND is_dead_arm=0 的 decided trades（net_pnl 非 None 非 0，
        exit_reason != 'unbuyable'），按 exit_date 周分桶（周一作 week_start），
        累积胜率 + Wilson CI + 双轴标签（n_decided/n_days）。

        返 [{week_start, win_rate, ci_low, ci_high, n_decided, n_total, n_days, label}]。
        空表返 []。口径：n_decided=Wilson CI 分母（与 _compute_arm_stats 一致排除 unbuyable/None/breakeven），
        n_days=唯一 exit_date 数（双轴标签用）。标签 robust 仅统计意义，不触发 sizing 调整（与
        lift_to_multiplier 脱节，R3 enforce 搁置）。
        """
        conn = self._conn()
        try:
            sql = """SELECT exit_date, net_pnl, exit_reason FROM trade_journal
                   WHERE is_realized=1 AND is_dead_arm=0
                     AND net_pnl IS NOT NULL AND net_pnl != 0
                     AND (exit_reason IS NULL OR exit_reason != 'unbuyable')
                     AND exit_date IS NOT NULL"""
            params: list = []
            if arm:
                sql += " AND arm = ?"
                params.append(arm)
            sql += " ORDER BY exit_date"
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        if not rows:
            return []

        from datetime import datetime, timedelta

        def _week_start(d_str: str) -> str:
            d = datetime.fromisoformat(d_str.split("T")[0])
            return (d - timedelta(days=d.weekday())).date().isoformat()

        # 累积：按 exit_date 排序，每条入累积池，按 week_start 取该周末累积快照
        by_week: dict[str, dict] = {}
        cum_n = 0
        cum_win = 0
        cum_days: set[str] = set()
        for r in rows:
            ws = _week_start(r["exit_date"])
            cum_n += 1
            if float(r["net_pnl"]) > 0:
                cum_win += 1
            cum_days.add(r["exit_date"].split("T")[0])
            by_week[ws] = {"n_decided": cum_n, "n_win": cum_win, "n_days": len(cum_days)}

        result: list[dict] = []
        for ws, d in sorted(by_week.items()):
            n_dec = d["n_decided"]
            n_days = d["n_days"]
            ci_low, ci_high = _wilson_ci(d["n_win"], n_dec)
            # 双轴标签：n<30 insufficient / n≥30 且 n_days<60 underpowered / n≥30 且 n_days≥60 robust
            if n_dec < 30:
                label = "insufficient_sample"
            elif n_days < 60:
                label = "underpowered"
            else:
                label = "robust"
            result.append({
                "week_start": ws,
                "win_rate": round(d["n_win"] / n_dec, 4) if n_dec else 0.0,
                "ci_low": ci_low, "ci_high": ci_high,
                "n_decided": n_dec, "n_total": n_dec, "n_days": n_days,
                "label": label,
            })
        return result

    def _distinct_arms(self) -> list[str]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT arm FROM trade_journal WHERE is_dead_arm=0"
            ).fetchall()
        finally:
            conn.close()
        return [r["arm"] for r in rows]

    def get_drawdown_status(self, arm: str | None = None) -> dict:
        """供 drawdown_breaker 调用的 equity + drawdown 快照。"""
        records = self.query_records(arm=arm, is_dead_arm=None)
        total_realized = sum(
            float(r.net_pnl) for r in records
            if r.is_realized and r.net_pnl is not None
        )
        total_unrealized = sum(
            float(r.unrealized_pnl) for r in records
            if r.unrealized_pnl is not None
        )
        cum = total_realized + total_unrealized
        # peak = max cumulative at any point (approximate from current + history)
        points = self.equity_curve(arm=arm)
        peak_pnl = max((p["cum_pnl"] for p in points), default=0.0)
        drawdown_cny = peak_pnl - cum
        dates = sorted({r.entry_date for r in records})
        return {
            "equity": round(DEFAULT_INITIAL_CAPITAL + cum, 2),
            "cum_pnl": round(cum, 2),
            "peak_pnl": round(peak_pnl, 2),
            "drawdown_cny": round(drawdown_cny, 2),
            "drawdown_pct": round(drawdown_cny / DEFAULT_INITIAL_CAPITAL * 100, 2)
            if DEFAULT_INITIAL_CAPITAL > 0 else 0.0,
            "days_tracked": len(dates),
            "n_records": len(records),
        }


# ── 统计方法论层（H1/H2，复用 s44_verifier 不重发明）──────────────────


def _wilson_ci(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """胜率 Wilson score interval（lower, upper）。

    比 normal approximation 更准（小 n 不 collapse to [0,0]）。
    空/零分母 → (0.0, 1.0)——宽带诚实暴露无数据（非 (0,0) 误导"精确 0%"），S183。
    """
    if total <= 0:
        return (0.0, 1.0)
    phat = wins / total
    n = total
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)


def _daily_aggregate_sharpe(
    net_pnls: list[float], exit_dates: list[str],
) -> dict:
    """H2 Sharpe 年化修正：先按 exit_date 日聚合 net_pnl → daily PnL 序列 →
    Sharpe = mean/std × sqrt(252)（日频年化有效）。

    per-trade × sqrt252 无效（低频臂如 floor 每年交易 <10 次，高估 ~16x）。
    """
    if not net_pnls or not exit_dates:
        return {"sharpe": None, "n_days": 0, "daily_mean": None, "daily_std": None}
    by_day: dict[str, float] = {}
    for pnl, date in zip(net_pnls, exit_dates):
        by_day[date] = by_day.get(date, 0.0) + pnl
    daily_pnls = list(by_day.values())
    if len(daily_pnls) < 2:
        return {"sharpe": None, "n_days": len(daily_pnls),
                "daily_mean": None, "daily_std": None}
    arr = np.array(daily_pnls, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    if std == 0:
        return {"sharpe": None, "n_days": len(daily_pnls),
                "daily_mean": round(mean, 4), "daily_std": 0.0}
    sharpe = mean / std * math.sqrt(252)
    return {
        "sharpe": round(sharpe, 4),
        "n_days": len(daily_pnls),
        "daily_mean": round(mean, 4),
        "daily_std": round(std, 4),
    }


def _compute_arm_stats(records: list[JournalRecord]) -> dict:
    """单臂统计封装（H1/H2/H8）。

    调 day_clustered_t_test + compute_dsr + compute_haircut +
    wilson_ci + daily_aggregate_sharpe + coverage_rate。
    underpowered gate：n_picks<30 或 n_days<60 → status='underpowered' 不出 kill。
    """
    if not records:
        return {"status": "empty", "n_picks": 0}

    # 分离 buyable / unbuyable（H8 coverage）
    buyable = [r for r in records if r.exit_reason != "unbuyable"]
    unbuyable = [r for r in records if r.exit_reason == "unbuyable"]
    n_buyable = len(buyable)
    n_unbuyable = len(unbuyable)
    n_total = len(records)
    coverage_rate = n_buyable / n_total if n_total > 0 else 0.0

    # execution winrate（只吃 buyable，unbuyable 不进分母 H8）
    wins = sum(1 for r in buyable if r.net_pnl is not None and r.net_pnl > 0)
    losses = sum(1 for r in buyable if r.net_pnl is not None and r.net_pnl < 0)
    n_decided = wins + losses
    execution_winrate = wins / n_decided if n_decided > 0 else None
    wr_lo, wr_hi = _wilson_ci(wins, n_decided) if n_decided > 0 else (0.0, 0.0)

    # net_pnl 序列
    net_pnls = [float(r.net_pnl) for r in buyable if r.net_pnl is not None]
    exit_dates = [r.exit_date or r.entry_date for r in buyable if r.net_pnl is not None]
    entry_dates = [r.entry_date for r in buyable if r.net_pnl is not None]
    total_net_pnl = sum(net_pnls)

    # 盈亏比
    win_pnls = [p for p in net_pnls if p > 0]
    loss_pnls = [p for p in net_pnls if p < 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = abs(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else None

    # day-clustered t-test（H1：防同日膨胀 n）
    t_result = None
    p_one_sided = None
    if net_pnls and exit_dates:
        t_result = day_clustered_t_test(net_pnls, exit_dates)
        if t_result is not None:
            p_one_sided = t_result.p_one_sided

    # Sharpe（H2：日聚合 + DSR + MinTRL）
    sharpe_info = _daily_aggregate_sharpe(net_pnls, exit_dates)
    dsr = None
    dsr_method = "N/A"
    min_trl = None
    if net_pnls:
        r_arr = np.array(net_pnls, dtype=float)
        dsr, dsr_method, min_trl = compute_dsr(r_arr, n_trials=4)

    # haircut
    haircut = None
    if net_pnls and len(net_pnls) >= 2:
        r_arr = np.array(net_pnls, dtype=float)
        haircut = compute_haircut(
            r_arr, n_obs=len(net_pnls), n_tests=1, method="bonferroni",
        )

    # underpowered gate（H1/H4）
    n_days = len(set(exit_dates)) if exit_dates else 0
    n_picks = n_buyable
    if n_picks < MIN_PICKS_FOR_KILL or n_days < MIN_DAYS_FOR_KILL:
        status = "underpowered"
    else:
        status = "enforced"

    return {
        "status": status,
        "n_picks": n_picks,
        "n_unbuyable": n_unbuyable,
        "n_days": n_days,
        "signal_coverage_rate": round(coverage_rate, 4),
        "execution_winrate": round(execution_winrate, 4) if execution_winrate is not None else None,
        "execution_winrate_ci": [wr_lo, wr_hi],
        "total_net_pnl": round(total_net_pnl, 2),
        "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio is not None else None,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        # day-clustered t-test
        "t_stat": t_result.t_stat if t_result else None,
        "p_one_sided": p_one_sided,
        "day_mean": t_result.day_mean if t_result else None,
        "day_std": t_result.day_std if t_result else None,
        # Sharpe
        "sharpe": sharpe_info["sharpe"],
        "sharpe_n_days": sharpe_info["n_days"],
        "dsr": dsr,
        "dsr_method": dsr_method,
        "min_trl": min_trl,
        "haircut": haircut,
        # 净超额 CI（day-clustered t-test 的 t_stat → 近似 CI）
        "net_excess_mean_cny": round(
            sum(net_pnls) / n_days if n_days > 0 and net_pnls else 0.0, 2),
    }


__all__ = [
    "TradeJournal",
    "JournalRecord",
    "PNL_UNIT_CNY",
    "DEFAULT_INITIAL_CAPITAL",
    "_wilson_ci",
    "_daily_aggregate_sharpe",
    "_compute_arm_stats",
]
