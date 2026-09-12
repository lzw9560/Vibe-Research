# -*- coding: utf-8 -*-
"""S173 Journal Recorder——orchestrator 顺序管线（非订阅/事件驱动）。

**C1 orchestrator 模式**（非订阅）：journal_recorder 显式调各臂 signal 生成器
→ 构造 Trades → Executor.execute → accounting 算 return → 写 trade_journal。
调用点：floor 臂在 build_position_batches 之后；breakout 臂在
select_premarket_candidates 之后；trend 臂在 select_trend_candidates 之后。
journal_recorder 在 signal 生成器返回后接管。

**C8 Trades 不加字段**：signal_id (UUID) + arm 由 journal_recorder 彔入
trade_journal 时赋值（journal_recorder 知道调了哪臂），不灌 Trades dataclass。
trade_journal 表是 source of truth。

**H9 batch 模式**（非 event-driven）：executor 只做 entry fill（executor.py:35-62
证实），无 exit fill 接口。journal_recorder 不等 executor exit events，改 batch：
call path_return → 一次性取完整 PathReturn → 写 journal。

**C2 成本分轨**：可平仓臂走 path_return(apply_cost=True)；gap 走 gap_net_return；
floor 走 mark-to-market（C3/C6 不走 path_return）。trend 与 breakout 同属可平仓臂
（path_return + stop/take/max_hold），仅 TREND_* params 不同。

**H3 单位统一**：pnl_unit 固定 CNY。可平仓臂 net_pnl = return_pct/100 × notional；
gap 臂 net_pnl = net_ratio × notional；floor 臂 unrealized_pnl = (close-entry)×shares。

**H7 gap-aware fill**：accounting.path_return 当前 stop/take 有乐观偏差
（gap-through 未建模）。不改 accounting.py 接口（只读约束），在 fills_json
记 optimism_flag + raw exit_price，文档化偏差量级。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable

from engine.trade_journal import TradeJournal, JournalRecord
from engine.accounting import path_return, gap_net_return, _find_signal_idx
from engine.executor import Executor
from engine.fill_policies import T1OpenFill
from engine.decision import Trades, FILL_T_PLUS_1_OPEN, FILL_ACCEPTED

_logger = logging.getLogger(__name__)

#: 默认臂列表（orchestrator 顺序调用）。
#: trend 臂（S181）接入——select_trend_candidates 已就绪，从 mock 升为可平仓实臂。
DEFAULT_ARMS: list[str] = ["floor", "breakout", "trend"]

#: breakout 臂 stop/take/max_hold 配置（premarket_selection HONEST_LABEL 制度）。
BREAKOUT_STOP_PCT: float = -4.0
BREAKOUT_TAKE_PCT: float = 8.0
BREAKOUT_MAX_HOLD: int = 3

#: trend swing 臂 stop/take/max_hold 配置（S181）。
#: 趋势波段比 breakout 持仓更久——更宽 stop（容噪声）/更大 take（追趋势）/更长 max_hold。
#: 初始值，待 trend_swing_arm spec grill 后校准。
TREND_STOP_PCT: float = -7.0
TREND_TAKE_PCT: float = 15.0
TREND_MAX_HOLD: int = 10

#: 默认 position size（股数，1 手=100 股）。
DEFAULT_SIZE: float = 100.0

#: paper 臂虚拟资本（H3 折算 CNY）。
VIRTUAL_CAPITAL: float = 100000.0


#: bars_provider 类型签名——给 code 返回 bars 列表（生产读 kline cache，测试 mock）。
BarsProvider = Callable[[str], list[dict]]


class JournalRecorder:
    """orchestrator 顺序管线——每日盘后闭环。

    依赖注入（可 mock）：
    - journal: TradeJournal（写 ledger）
    - executor: Executor（entry fill）
    - bars_provider: 给 code 返回 bars（生产读 kline cache）
    """

    def __init__(
        self, journal: TradeJournal | None = None,
        executor: Executor | None = None,
        bars_provider: BarsProvider | None = None,
    ) -> None:
        self._journal = journal or TradeJournal()
        self._executor = executor or Executor()
        self._bars_provider = bars_provider or (lambda _code: [])

    def record_t0_fill(
        self, signal_id: str, fill_type: str, price: float, ts: str,
        size: int = 100, date: str = "",
    ) -> dict:
        """S189 T3 · 记 T+0 fill 到 trade_journal.fills_json（同日买/卖 pair）。

        fill_type: 'buy'（买压升→买 100 股可卖旧仓）/ 'sell'（买压降→卖 100 回补）。
        fills_json 追加 t0_fills list[{type, price, ts, size, date}]。
        返 {signal_id, fill_type, n_t0_fills}。
        """
        import json  # noqa: PLC0415
        from engine.trade_journal import TradeJournal  # noqa: PLC0415
        journal = self._journal if isinstance(self._journal, TradeJournal) else TradeJournal()
        conn = journal._conn()  # type: ignore[attr-defined]
        try:
            row = conn.execute(
                "SELECT fills_json FROM trade_journal WHERE signal_id=?", (signal_id,)
            ).fetchone()
            if not row:
                return {"error": f"signal_id {signal_id} 不存在"}
            fills = json.loads(row["fills_json"]) if row["fills_json"] else {}
            t0_list = fills.get("t0_fills", [])
            t0_list.append({"type": fill_type, "price": price, "ts": ts, "size": size, "date": date})
            fills["t0_fills"] = t0_list
            conn.execute(
                "UPDATE trade_journal SET fills_json=? WHERE signal_id=?",
                (json.dumps(fills, ensure_ascii=False), signal_id),
            )
            conn.commit()
            return {"signal_id": signal_id, "fill_type": fill_type, "n_t0_fills": len(t0_list)}
        finally:
            conn.close()

    def run_daily(
        self, target_date: str | None = None,
        arms: list[str] | None = None,
    ) -> dict:
        """每日盘后闭环管线（C1 orchestrator 顺序调用，非订阅）。

        arms 默认 ['floor','breakout','trend']；limitup/gap mock。
        返 {arm: {n_candidates, n_buyable, n_unbuyable, n_realized}}。
        """
        arms = arms or DEFAULT_ARMS
        if target_date is None:
            from vr_paths import prev_trading_date_str  # noqa: PLC0415
            target_date = prev_trading_date_str()  # S175 R4：T-1 信号日，T1OpenFill 在 T 成交（C5 fix no_t1_bar 误标 unbuyable）

        _logger.info("journal_recorder run_daily target_date=%s arms=%s", target_date, arms)

        # S175 R3：settle_pending 先重算昨日未平 'hold'（path_return T+1 guard 需 T+2+ bars）
        self.settle_pending_breakout()
        self.settle_pending_trend()

        results: dict[str, Any] = {}
        for arm in arms:
            try:
                if arm == "floor":
                    results[arm] = self._process_floor(target_date)
                elif arm == "breakout":
                    results[arm] = self._process_breakout(target_date)
                elif arm == "trend":
                    results[arm] = self._process_trend(target_date)
                elif arm == "gap":
                    results[arm] = self._process_gap(target_date)
                elif arm == "limitup":
                    results[arm] = self._process_mock_arm(arm, target_date)
                else:
                    results[arm] = {"status": "unknown_arm", "n_candidates": 0}
            except Exception as e:  # noqa: BLE001
                _logger.warning("journal_recorder arm=%s failed: %s", arm, e)
                results[arm] = {"status": "error", "error": str(e), "n_candidates": 0}
        return results

    # ── S175 R3 settle_pending_breakout（重算昨日 'hold'，C2/SH5）─────────

    def settle_pending_breakout(self) -> dict:
        """S175 R3 — 重算昨日未平 breakout 'hold' 记录（C2/SH5/SH7）。

        path_return T+1 guard（accounting.py:120 idx+2>=len→None）需 T+2+ 天 bar——
        盘后 T 跑 breakout 全记 is_realized=0 'hold'。次日 bars 增长后，此方法回头
        重算：query is_realized=0 'hold' → bars_provider 取 bars（已含 T+2+）→
        path_return → 若完整 exit（非截断 max_hold）→ INSERT OR REPLACE **同 signal_id**
        （绕过 .create() 生新 UUID）更新 is_realized=1 + net_pnl + exit_price=pr.exit_price。

        **截断 max_hold（SH5）**：path_return max_hold exit（accounting.py:170
        exit_idx=min(idx+1+max_hold_days, len-1)）在 bars 不足完整持仓期时截断返非 None
        PathReturn。须检测 signal_idx+2+max_hold > len(bars) → 留 hold 等更多 bars，
        否则过早标 realized 后续 stop/take 永不检查 → 胜率错。

        **signal_id bypass .create()**：JournalRecord.create()（trade_journal.py:94）
        硬编 signal_id=str(uuid.uuid4())，cls(signal_id=uuid,...,**kwargs) 传 signal_id
        会 TypeError（multiple values）。直接构造 JournalRecord(signal_id=pos.signal_id)
        绕过 .create()，复用原 id 做 INSERT OR REPLACE 幂等更新。
        """
        pending = self._journal.query_records(arm="breakout", is_realized=0, is_dead_arm=0)
        # query_records 无 exit_reason 参数（trade_journal.py:197），Python 层 filter
        holds = [r for r in pending if r.exit_reason == "hold"]
        n_settled = 0
        for pos in holds:
            if pos.entry_price is None:
                continue
            bars = self._bars_provider(pos.stock_code)
            if not bars:
                continue
            # 构造已 filled Trades（entry_price 预填，不走 Executor——entry 已知 from 'hold' 记录）
            trades = Trades(
                code=pos.stock_code,
                signal_date=pos.entry_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=DEFAULT_SIZE,
                entry_price=float(pos.entry_price),
                fill_status=FILL_ACCEPTED,
            )
            pr = path_return(
                trades, bars,
                stop_pct=BREAKOUT_STOP_PCT,
                take_profit_pct=BREAKOUT_TAKE_PCT,
                max_hold_days=BREAKOUT_MAX_HOLD,
                apply_cost=True,
            )
            if pr is None:
                continue  # 仍 bars 不足，留 hold
            # 截断检测：max_hold exit 且 bars 不足完整持仓期 → 留 hold（SH5）
            if pr.exit_reason == "max_hold":
                signal_idx = _find_signal_idx(bars, pos.entry_date)
                if signal_idx is not None and signal_idx + 2 + BREAKOUT_MAX_HOLD > len(bars):
                    continue  # 截断 max_hold，留 hold 等更多 bars
            # 标 realized——INSERT OR REPLACE 同 signal_id（绕过 .create()）
            position_notional = float(pos.entry_price) * DEFAULT_SIZE
            net_pnl = pr.return_pct / 100.0 * position_notional
            record = JournalRecord(
                signal_id=pos.signal_id,  # bypass .create()——复用原 id 做 INSERT OR REPLACE
                arm="breakout", stock_code=pos.stock_code,
                entry_price=pos.entry_price, entry_date=pos.entry_date,
                exit_price=pr.exit_price, exit_date=pr.exit_date,
                exit_reason=pr.exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=pr.cost_pct, gross_return=pr.gross_return_pct,
                is_realized=1,
                fills_json=json.dumps({
                    "won": pr.won,
                    "return_pct": pr.return_pct,
                    "exit_reason": pr.exit_reason,
                    "exit_date": pr.exit_date,
                    "exit_price": pr.exit_price,
                    "cost_pct": pr.cost_pct,
                    "gross_return_pct": pr.gross_return_pct,
                    "optimism_flag": "gap_through_unmodeled",
                    "settled_by": "settle_pending_breakout",
                    "position_notional": round(position_notional, 2),
                }),
                created_at=pos.created_at,  # 保留原 created_at
            )
            self._journal.insert(record)  # INSERT OR REPLACE 同 signal_id 幂等
            n_settled += 1
        return {"n_pending": len(holds), "n_settled": n_settled}

    # ── S181 settle_pending_trend（仿 settle_pending_breakout，换 TREND_* params）──

    def settle_pending_trend(self) -> dict:
        """S181 — 重算昨日未平 trend 'hold' 记录（仿 settle_pending_breakout）。

        与 breakout 同属可平仓臂（path_return + stop/take/max_hold），仅 params 不同：
        TREND_STOP_PCT/TREND_TAKE_PCT/TREND_MAX_HOLD 更宽（趋势波段容噪声/追趋势/持仓更久）。

        逻辑同 settle_pending_breakout：query is_realized=0 arm='trend' exit_reason='hold'
        → 重算 path_return(TREND_*) → 截断 max_hold 检测 → INSERT OR REPLACE 同 signal_id。
        """
        pending = self._journal.query_records(arm="trend", is_realized=0, is_dead_arm=0)
        holds = [r for r in pending if r.exit_reason == "hold"]
        n_settled = 0
        for pos in holds:
            if pos.entry_price is None:
                continue
            bars = self._bars_provider(pos.stock_code)
            if not bars:
                continue
            trades = Trades(
                code=pos.stock_code,
                signal_date=pos.entry_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=DEFAULT_SIZE,
                entry_price=float(pos.entry_price),
                fill_status=FILL_ACCEPTED,
            )
            pr = path_return(
                trades, bars,
                stop_pct=TREND_STOP_PCT,
                take_profit_pct=TREND_TAKE_PCT,
                max_hold_days=TREND_MAX_HOLD,
                apply_cost=True,
            )
            if pr is None:
                continue  # 仍 bars 不足，留 hold
            # 截断检测：max_hold exit 且 bars 不足完整持仓期 → 留 hold（SH5 同 breakout）
            if pr.exit_reason == "max_hold":
                signal_idx = _find_signal_idx(bars, pos.entry_date)
                if signal_idx is not None and signal_idx + 2 + TREND_MAX_HOLD > len(bars):
                    continue  # 截断 max_hold，留 hold 等更多 bars
            position_notional = float(pos.entry_price) * DEFAULT_SIZE
            net_pnl = pr.return_pct / 100.0 * position_notional
            record = JournalRecord(
                signal_id=pos.signal_id,  # bypass .create()——复用原 id 做 INSERT OR REPLACE
                arm="trend", stock_code=pos.stock_code,
                entry_price=pos.entry_price, entry_date=pos.entry_date,
                exit_price=pr.exit_price, exit_date=pr.exit_date,
                exit_reason=pr.exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=pr.cost_pct, gross_return=pr.gross_return_pct,
                is_realized=1,
                fills_json=json.dumps({
                    "won": pr.won,
                    "return_pct": pr.return_pct,
                    "exit_reason": pr.exit_reason,
                    "exit_date": pr.exit_date,
                    "exit_price": pr.exit_price,
                    "cost_pct": pr.cost_pct,
                    "gross_return_pct": pr.gross_return_pct,
                    "optimism_flag": "gap_through_unmodeled",
                    "settled_by": "settle_pending_trend",
                    "position_notional": round(position_notional, 2),
                }),
                created_at=pos.created_at,  # 保留原 created_at
            )
            self._journal.insert(record)  # INSERT OR REPLACE 同 signal_id 幂等
            n_settled += 1
        return {"n_pending": len(holds), "n_settled": n_settled}

    # ── breakout 臂（可平仓臂，C2 path_return）─────────────────────────

    def _process_breakout(self, target_date: str) -> dict:
        """breakout 臂：select_premarket_candidates → Trades → execute → path_return。

        1. select_premarket_candidates(target_date) → candidates
        2. 构造 Trades(code, signal_date, fill_type=t1_open, direction=long, size=100)
           （C8：不带 signal_id/arm）
        3. Executor.execute(T1OpenFill) → entry fill
        4. 涨停买不到 → survivorship 过滤 → exit_reason='unbuyable'
        5. accounting.path_return(apply_cost=True) → PathReturn
        6. net_pnl = return_pct/100 × position_notional (CNY)
        7. trade_journal.insert(is_realized=1)
        """
        from strategies.premarket_selection import select_premarket_candidates  # noqa: PLC0415

        candidates = select_premarket_candidates(target_date)
        n_unbuyable = 0
        n_buyable = 0
        n_realized = 0

        for cand in candidates:
            bars = self._bars_provider(cand.code)
            if not bars:
                continue

            trades = Trades(
                code=cand.code,
                signal_date=target_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=DEFAULT_SIZE,
            )
            filled = self._executor.execute(trades, bars, T1OpenFill())

            if not filled.is_accepted():
                # survivorship 过滤：涨停买不到（A5）
                record = JournalRecord.create(
                    arm="breakout", stock_code=cand.code,
                    entry_price=None, entry_date=target_date,
                    exit_reason="unbuyable", is_realized=1,
                    fills_json=json.dumps({
                        "fill_status": filled.fill_status,
                        "fill_reason": filled.fill_reason,
                    }),
                )
                self._journal.insert(record)
                n_unbuyable += 1
                continue

            n_buyable += 1
            pr = path_return(
                filled, bars,
                stop_pct=BREAKOUT_STOP_PCT,
                take_profit_pct=BREAKOUT_TAKE_PCT,
                max_hold_days=BREAKOUT_MAX_HOLD,
                apply_cost=True,
            )
            if pr is None:
                # T+1 guard 或数据不足 → 仍录 entry，标 unrealized
                record = JournalRecord.create(
                    arm="breakout", stock_code=cand.code,
                    entry_price=filled.entry_price, entry_date=target_date,
                    exit_reason="hold", is_realized=0,
                    fills_json=json.dumps({
                        "fill_status": filled.fill_status,
                        "optimism_flag": "path_return_none_t1_guard",
                    }),
                )
                self._journal.insert(record)
                continue

            position_notional = float(filled.entry_price) * DEFAULT_SIZE
            net_pnl = pr.return_pct / 100.0 * position_notional
            gross_pnl = pr.gross_return_pct / 100.0 * position_notional

            record = JournalRecord.create(
                arm="breakout", stock_code=cand.code,
                entry_price=filled.entry_price, entry_date=target_date,
                exit_price=pr.exit_price,  # S175 R6：PathReturn.exit_price（T2 三分支均设），非 position_notional/DEFAULT_SIZE=entry_price bug
                exit_date=pr.exit_date, exit_reason=pr.exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=pr.cost_pct,
                gross_return=pr.gross_return_pct,
                is_realized=1,
                fills_json=json.dumps({
                    "won": pr.won,
                    "return_pct": pr.return_pct,
                    "exit_reason": pr.exit_reason,
                    "exit_date": pr.exit_date,
                    "cost_pct": pr.cost_pct,
                    "gross_return_pct": pr.gross_return_pct,
                    "optimism_flag": "gap_through_unmodeled",
                    "raw_exit_reason": pr.exit_reason,
                    "position_notional": round(position_notional, 2),
                }),
            )
            self._journal.insert(record)
            n_realized += 1

        return {
            "n_candidates": len(candidates),
            "n_buyable": n_buyable,
            "n_unbuyable": n_unbuyable,
            "n_realized": n_realized,
        }

    # ── trend 臂（可平仓臂，S181，仿 _process_breakout 换 TREND_* params）──────

    def _process_trend(self, target_date: str) -> dict:
        """trend swing 臂（S181）：select_trend_candidates → Trades → execute → path_return。

        仿 _process_breakout，仅 signal 生成器与 stop/take/max_hold params 不同：
        1. select_trend_candidates(target_date) → candidates（接口返 list[{code,name}]，
           防御兼容 dataclass .code 与 dict["code"]——trend_swing_arm 接口未定时兜底）
        2. 构造 Trades(code, signal_date, fill_type=t1_open, direction=long, size=100)
           （C8：不带 signal_id/arm）
        3. Executor.execute(T1OpenFill) → entry fill
        4. 涨停买不到 → survivorship 过滤 → exit_reason='unbuyable'
        5. accounting.path_return(TREND_*，apply_cost=True) → PathReturn
        6. net_pnl = return_pct/100 × position_notional (CNY)
        7. trade_journal.insert(is_realized=1)
        """
        from strategies.trend_swing_arm import select_trend_candidates  # noqa: PLC0415

        candidates = select_trend_candidates(target_date)
        n_unbuyable = 0
        n_buyable = 0
        n_realized = 0

        for cand in candidates:
            code = self._cand_code(cand)
            if not code:
                continue
            bars = self._bars_provider(code)
            if not bars:
                continue

            trades = Trades(
                code=code,
                signal_date=target_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=DEFAULT_SIZE,
            )
            filled = self._executor.execute(trades, bars, T1OpenFill())

            if not filled.is_accepted():
                # survivorship 过滤：涨停买不到（A5）
                record = JournalRecord.create(
                    arm="trend", stock_code=code,
                    entry_price=None, entry_date=target_date,
                    exit_reason="unbuyable", is_realized=1,
                    fills_json=json.dumps({
                        "fill_status": filled.fill_status,
                        "fill_reason": filled.fill_reason,
                    }),
                )
                self._journal.insert(record)
                n_unbuyable += 1
                continue

            n_buyable += 1
            pr = path_return(
                filled, bars,
                stop_pct=TREND_STOP_PCT,
                take_profit_pct=TREND_TAKE_PCT,
                max_hold_days=TREND_MAX_HOLD,
                apply_cost=True,
            )
            if pr is None:
                # T+1 guard 或数据不足 → 仍录 entry，标 unrealized
                record = JournalRecord.create(
                    arm="trend", stock_code=code,
                    entry_price=filled.entry_price, entry_date=target_date,
                    exit_reason="hold", is_realized=0,
                    fills_json=json.dumps({
                        "fill_status": filled.fill_status,
                        "optimism_flag": "path_return_none_t1_guard",
                    }),
                )
                self._journal.insert(record)
                continue

            position_notional = float(filled.entry_price) * DEFAULT_SIZE
            net_pnl = pr.return_pct / 100.0 * position_notional
            gross_pnl = pr.gross_return_pct / 100.0 * position_notional

            record = JournalRecord.create(
                arm="trend", stock_code=code,
                entry_price=filled.entry_price, entry_date=target_date,
                exit_price=pr.exit_price,  # PathReturn.exit_price（T2 三分支均设）
                exit_date=pr.exit_date, exit_reason=pr.exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=pr.cost_pct,
                gross_return=pr.gross_return_pct,
                is_realized=1,
                fills_json=json.dumps({
                    "won": pr.won,
                    "return_pct": pr.return_pct,
                    "exit_reason": pr.exit_reason,
                    "exit_date": pr.exit_date,
                    "cost_pct": pr.cost_pct,
                    "gross_return_pct": pr.gross_return_pct,
                    "optimism_flag": "gap_through_unmodeled",
                    "raw_exit_reason": pr.exit_reason,
                    "position_notional": round(position_notional, 2),
                    "arm_params": {
                        "stop_pct": TREND_STOP_PCT,
                        "take_pct": TREND_TAKE_PCT,
                        "max_hold": TREND_MAX_HOLD,
                    },
                }),
            )
            self._journal.insert(record)
            n_realized += 1

        return {
            "n_candidates": len(candidates),
            "n_buyable": n_buyable,
            "n_unbuyable": n_unbuyable,
            "n_realized": n_realized,
        }

    # ── floor 臂（C3/C6 MTM 分轨）───────────────────────────────────────

    def _process_floor(self, target_date: str) -> dict:
        """floor 臂（C3/C6 MTM 分轨）：

        1. build_position_batches() → ETF batches
        2. 构造 Trades(code=ETF, signal_date, fill_type=t1_open, direction=long, size)
        3. Executor.execute(T1OpenFill) → entry fill
        4. exit_reason='hold'（不主动平仓，C3）
        5. unrealized_pnl = (current_close - entry_price) × shares（每日 MTM 更新）
        6. trade_journal.insert(is_realized=0)
        """
        from strategies.index_replication_floor import (  # noqa: PLC0415
            build_position_batches, ETF_CODE)

        batches = build_position_batches(one_shot=True, start_date=target_date)
        if not batches:
            return {"n_candidates": 0, "n_buyable": 0, "n_unbuyable": 0, "n_realized": 0}

        # floor 是 ETF 复制（S172 ETF_CODE='512890' 红利低波；S175 R5 fix 510300 硬编 bug C1）
        etf_code = ETF_CODE
        bars = self._bars_provider(etf_code)
        n_realized = 0

        for batch in batches:
            batch_date = batch.get("date", target_date)
            amount = float(batch.get("amount", 0))

            trades = Trades(
                code=etf_code,
                signal_date=batch_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=DEFAULT_SIZE,
            )
            filled = self._executor.execute(trades, bars, T1OpenFill())

            if not filled.is_accepted() or filled.entry_price is None:
                record = JournalRecord.create(
                    arm="floor", stock_code=etf_code,
                    entry_price=None, entry_date=batch_date,
                    exit_reason="unbuyable", is_realized=1,
                    fills_json=json.dumps({
                        "fill_status": filled.fill_status,
                        "fill_reason": filled.fill_reason,
                        "batch_amount": amount,
                    }),
                )
                self._journal.insert(record)
                continue

            # C3/C6：floor 不走 path_return，走 mark-to-market
            entry_price = float(filled.entry_price)
            # 当前 close（从 bars 取最新）
            current_close = self._latest_close(bars, target_date=target_date)
            unrealized_pnl = None
            if current_close is not None:
                unrealized_pnl = round((current_close - entry_price) * DEFAULT_SIZE, 2)

            record = JournalRecord.create(
                arm="floor", stock_code=etf_code,
                entry_price=entry_price, entry_date=batch_date,
                exit_reason="hold",  # C3：不主动平仓
                is_realized=0,
                unrealized_pnl=unrealized_pnl,
                gross_return=round((current_close - entry_price) / entry_price * 100, 4)
                if current_close and entry_price else None,
                fills_json=json.dumps({
                    "fill_status": filled.fill_status,
                    "batch_amount": amount,
                    "entry_commission_only": True,
                    "mtm_track": "floor_c3_c6",
                }),
            )
            self._journal.insert(record)
            n_realized += 1

        return {
            "n_candidates": len(batches),
            "n_buyable": n_realized,
            "n_unbuyable": len(batches) - n_realized,
            "n_realized": 0,  # floor is_realized=0
        }

    def update_floor_mtm(self, target_date: str | None = None) -> int:
        """每日盘后更新 floor 臂 unrealized_pnl（C6）。

        按 ETF close 重算 unrealized_pnl = (current_close - entry_price) × shares。
        """
        open_positions = self._journal.query_records(
            arm="floor", is_realized=0, is_dead_arm=None,
        )
        updated = 0
        for pos in open_positions:
            if pos.entry_price is None:
                continue
            bars = self._bars_provider(pos.stock_code)
            current_close = self._latest_close(bars, target_date=target_date)
            if current_close is None:
                continue
            unrealized = round(
                (current_close - float(pos.entry_price)) * DEFAULT_SIZE, 2,
            )
            if self._journal.update_unrealized(pos.signal_id, unrealized, current_close):
                updated += 1
        return updated

    # ── gap 臂（falsified dead_arm，C2 gap_net_return）──────────────────

    def _process_gap(self, target_date: str) -> dict:
        """gap 臂（falsified dead_arm，保留录数据）：

        1. mock signal (entry/exit price + date)
        2. accounting.gap_net_return(entry, exit, entry_date, size) → (net_ratio, cost_pct, gross_ratio)
        3. net_pnl = net_ratio × position_notional (CNY)
        4. trade_journal.insert(is_realized=1, is_dead_arm=1)
        """
        # gap 臂 mock：用 kline cache 取 D close → D+1 open（若可取）
        # 此处 mock 不联网，生产接线后从 kline cache 取真价
        mock_entry = 10.0
        mock_exit = 10.13  # +1.3% gross（§44 gap edge 教训）
        position_notional = mock_entry * DEFAULT_SIZE

        net_ratio, cost_pct, gross_ratio = gap_net_return(
            mock_entry, mock_exit, entry_date=target_date, size=DEFAULT_SIZE,
        )
        net_pnl = net_ratio * position_notional

        record = JournalRecord.create(
            arm="gap", stock_code="mock_gap",
            entry_price=mock_entry, entry_date=target_date,
            exit_price=mock_exit, exit_date=target_date,
            exit_reason="signal",
            net_pnl=round(net_pnl, 2),
            cost_pct=cost_pct,
            gross_return=round(gross_ratio * 100, 4),
            is_realized=1,
            is_dead_arm=1,  # gap falsified，不参与聚合胜率但保留录
            fills_json=json.dumps({
                "net_ratio": net_ratio,
                "gross_ratio": gross_ratio,
                "cost_pct": cost_pct,
                "position_notional": position_notional,
                "note": "gap falsified (§44 cost illusion), retained for audit",
            }),
        )
        self._journal.insert(record)
        return {
            "n_candidates": 1,
            "n_buyable": 1,
            "n_unbuyable": 0,
            "n_realized": 1,
        }

    # ── mock 臂（limitup paper）─────────────────────────────────────────

    def _process_mock_arm(self, arm: str, target_date: str) -> dict:
        """limitup paper 臂 mock signal 录入（A1：4 臂都能录到 trade_journal）。

        生产接线后调真实 signal 生成器。mock 不臆造 return——标 underpowered。
        trend 已于 S181 升为实臂（_process_trend），此处仅 limitup 残留 mock。
        """
        record = JournalRecord.create(
            arm=arm, stock_code=f"mock_{arm}",
            entry_price=10.0, entry_date=target_date,
            exit_reason="hold", is_realized=0,
            is_dead_arm=0,
            fills_json=json.dumps({
                "mock": True,
                "note": f"{arm} paper arm, signal generator not yet wired",
            }),
        )
        self._journal.insert(record)
        return {
            "n_candidates": 1,
            "n_buyable": 1,
            "n_unbuyable": 0,
            "n_realized": 0,
        }

    # ── 辅助 ──────────────────────────────────────────────────────────

    @staticmethod
    def _cand_code(cand: Any) -> str | None:
        """从候选对象取 code——兼容 dataclass(.code) 与 dict(["code"])。

        trend_swing_arm.select_trend_candidates 接口未定（上一个 agent 起草中），
        声明返 list[{code,name}]。breakout 的 PreMarketCandidate 是 dataclass 用 .code；
        若 trend 返 dict 则走 ["code"]。此处防御兜底，接口定稿后可简化。
        """
        code = getattr(cand, "code", None)
        if code is None and isinstance(cand, dict):
            code = cand.get("code")
        return str(code) if code else None

    @staticmethod
    def _latest_close(bars: list[dict], target_date: str | None = None) -> float | None:
        """从 bars 取最新 close（日线倒序或正序兼容）。

        S175 R4b（SH2）：target_date 过滤——只返 date<=target_date 的最后一根 bar
        close，防历史重跑（run_daily(target_date='2026-09-01')）用未来 close 前视偏差。
        target_date=None 时不限（生产当日跑安全，bars 最后=当日）。
        """
        if not bars:
            return None
        candidates = bars
        if target_date is not None:
            candidates = [
                b for b in bars
                if str(b.get("date", "") if isinstance(b, dict) else "")[:10] <= target_date
            ]
            if not candidates:
                return None
        for bar in reversed(candidates):
            close = bar.get("close") if isinstance(bar, dict) else None
            try:
                close_f = float(close) if close else 0.0
            except (TypeError, ValueError):
                close_f = 0.0
            if close_f > 0:
                return close_f
        return None


__all__ = [
    "JournalRecorder",
    "DEFAULT_ARMS",
    "BREAKOUT_STOP_PCT",
    "BREAKOUT_TAKE_PCT",
    "BREAKOUT_MAX_HOLD",
    "TREND_STOP_PCT",
    "TREND_TAKE_PCT",
    "TREND_MAX_HOLD",
]
