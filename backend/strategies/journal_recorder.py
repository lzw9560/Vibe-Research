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

**H7 gap-aware fill**：S201b stage 2 修复——accounting.path_return stop 分支已实现
gap-through-aware fill（open<=stop→fill=open, low<=stop→fill=stop*(1-eps)）+
一字跌停 sellability check。新 gross 写 gross_return_v2（冻结 gross_return 不动），
exit_model_version="v2_gap_through_aware" 标记版本。
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
#: S211 consecutive_relay 臂（lbc>=2 连板接力，overnight gap path，regime-stratified cap）。
DEFAULT_ARMS: list[str] = ["floor", "breakout", "trend", "consecutive_relay"]

#: breakout 臂 stop/take/max_hold 配置（premarket_selection HONEST_LABEL 制度）。
BREAKOUT_STOP_PCT: float = -4.0
BREAKOUT_TAKE_PCT: float = 8.0
BREAKOUT_MAX_HOLD: int = 3

#: S209 T10 post_first_board 臂（探索性 PAPER，继承 breakout 冻结 -4/+8/3 @ 74295b9，不新 sweep）。
#: 前提证伪（ashare-practitioner）：breakout +0.36% net 是 5元佣金门+regime 假象→net=-0.30%；
#: 本臂 exploratory 自证 net edge，不继承假阳性。lift_mult=0.5 underpowered cap。
POST_FIRST_BOARD_STOP_PCT: float = -4.0
POST_FIRST_BOARD_TAKE_PCT: float = 8.0
POST_FIRST_BOARD_MAX_HOLD: int = 3

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
        from engine.paper_portfolio import PaperPortfolio  # noqa: PLC0415
        self._portfolio = PaperPortfolio(self._journal)

    def _arm_size(self, arm: str, base: float = DEFAULT_SIZE, regime: str | None = None) -> float:
        """T4（S209 §4）：§44 lift cap 真咬仓位——接 PaperPortfolio.final_size 4-layer。

        breakout/trend/post_first_board lift=0.5（未validated/探索性）→ 50 股（halve）。
        floor/gap/mock lift=1.0 → 100 股（N/A 不缩）。
        intraday_mult MVP=1.0（v2 接 per-code 单笔浮亏 state）。
        arm_mult/port_mult days<60→1.0 underpowered（DrawdownBreaker H4）。

        S211：regime 参数支持 consecutive_relay regime-stratified caps
        （bull ×0.75 provisional / bear+range ×0.5；2026-09-18 核 evaluation.py:89-103 registry_caps）。regime=None → 保守 weight_multiplier。
        """
        return max(self._portfolio.final_size(arm, base, regime=regime), 0.0)

    # record_t0_fill 已删（v3 P0-4，2026-09-20）：死代码零生产调用（grep 核实），
    # manual_trade 走 manual_trades.jsonl 平行路径非 trade_journal.fills_json。
    # 原设计要求 signal_id 在 trade_journal 表存在，但 manual_trade 的 reference_signal_id
    # 不在该表 → wire 会返"signal_id 不存在"。详见 audit-2026-09-20-v3。

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
        self.settle_pending_consecutive_relay()

        results: dict[str, Any] = {}
        for arm in arms:
            try:
                if arm == "floor":
                    results[arm] = self._process_floor(target_date)
                elif arm == "breakout":
                    results[arm] = self._process_breakout(target_date)
                elif arm == "post_first_board":
                    results[arm] = self._process_post_first_board(target_date)
                elif arm == "trend":
                    results[arm] = self._process_trend(target_date)
                elif arm == "consecutive_relay":
                    results[arm] = self._process_consecutive_relay(target_date)
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
        path_return → 若完整 exit（非截断 max_hold）→ update_settlement_v2（UPDATE 非
        INSERT OR REPLACE）更新 is_realized=1 + gross_return_v2 + exit_model_version。
        冻结 gross_return 不动（S201b stage 2 版本保留）。

        **截断 max_hold（SH5）**：path_return max_hold exit（accounting.py:170
        exit_idx=min(idx+1+max_hold_days, len-1)）在 bars 不足完整持仓期时截断返非 None
        PathReturn。须检测 signal_idx+2+max_hold > len(bars) → 留 hold 等更多 bars，
        否则过早标 realized 后续 stop/take 永不检查 → 胜率错。

        **S201b stage 2 版本保留**：绝不 INSERT OR REPLACE（spec verdict #6：覆盖全字段
        无 before-image 违 reproducibility）。update_settlement_v2 只 UPDATE 指定字段
        （gross_return_v2/exit_price/exit_reason/net_pnl/cost_pct/is_realized/exit_model_version），
        保留 gross_return + fills_json + created_at 不变。
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
            # S201b stage 2: 标 realized——用 update_settlement_v2（UPDATE 非 INSERT OR REPLACE）
            # 冻结 gross_return 不动，新 gross 写 gross_return_v2 + exit_model_version
            position_notional = float(pos.entry_price) * self._arm_size("breakout")
            net_pnl = pr.return_pct / 100.0 * position_notional
            updated = self._journal.update_settlement_v2(
                signal_id=pos.signal_id,
                gross_return_v2=pr.gross_return_pct,
                exit_price=pr.exit_price,
                exit_date=pr.exit_date,
                exit_reason=pr.exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=pr.cost_pct,
                exit_model_version="v2_gap_through_aware",
            )
            if updated:
                n_settled += 1
        return {"n_pending": len(holds), "n_settled": n_settled}

    # ── S181 settle_pending_trend（仿 settle_pending_breakout，换 TREND_* params）──

    def settle_pending_trend(self) -> dict:
        """S181 — 重算昨日未平 trend 'hold' 记录（仿 settle_pending_breakout）。

        与 breakout 同属可平仓臂（path_return + stop/take/max_hold），仅 params 不同：
        TREND_STOP_PCT/TREND_TAKE_PCT/TREND_MAX_HOLD 更宽（趋势波段容噪声/追趋势/持仓更久）。

        逻辑同 settle_pending_breakout：query is_realized=0 arm='trend' exit_reason='hold'
        → 重算 path_return(TREND_*) → 截断 max_hold 检测 → update_settlement_v2（S201b stage 2）。
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
            position_notional = float(pos.entry_price) * self._arm_size("trend")
            net_pnl = pr.return_pct / 100.0 * position_notional
            # S201b stage 2: update_settlement_v2（UPDATE 非 INSERT OR REPLACE，冻结 gross_return）
            updated = self._journal.update_settlement_v2(
                signal_id=pos.signal_id,
                gross_return_v2=pr.gross_return_pct,
                exit_price=pr.exit_price,
                exit_date=pr.exit_date,
                exit_reason=pr.exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=pr.cost_pct,
                exit_model_version="v2_gap_through_aware",
            )
            if updated:
                n_settled += 1
        return {"n_pending": len(holds), "n_settled": n_settled}

    # ── S211 consecutive_relay 臂（overnight gap path，regime-stratified cap）──

    def _regime_for_date(self, date: str) -> str | None:
        """S211: 查 date 的 MA20 3-way regime（bull/bear/range）。

        懒 load compute_regime_labels（cache index_ma20_regime.json）。失败/无 cache → None
        （保守 ×0.5 cap）。session 内 cache 避免重复 load。
        """
        if not hasattr(self, "_regime_cache") or self._regime_cache is None:
            try:
                from tools.gap_regime_stratified import compute_regime_labels  # noqa: PLC0415
                self._regime_cache = compute_regime_labels() or {}
            except Exception as e:  # noqa: BLE001
                _logger.warning("compute_regime_labels 失败（regime=None 保守）: %s", e)
                self._regime_cache = {}
        return self._regime_cache.get(date)

    def _resolve_gap_exit(
        self, bars: list[dict], d_idx: int, code: str,
    ) -> tuple[float | None, str | None, dict]:
        """找 overnight gap 平仓的 exit price/date——D+1 一字跌停封死时找限跌打开日 open。

        realizability-bias 修（2026-09-19）：原 gap 口径 naive 用 open[D+1] 作 exit。
        但 D+1 一字跌停封死时 open[D+1] 是 locked 价（卖不掉）——实际要在限跌打开日
        （D+1 后首个非一字跌停 bar）的 open 才能卖。naive 口径 per-pick over-credit
        ~11%（locked picks paper -10% 但实际 -15%+）。

        - 正常（D+1 非一字跌停）→ exit = open[D+1]（原 overnight gap 口径, backward compat）。
        - D+1 一字跌停封死 + 限跌打开日存在 → exit = open[打开日]（实际可卖价）。
        - D+1 一字跌停封死 + 一直封死到 cache 末 → (None, None, info) 卖不掉, 诚实记
          None 不臆造（is_realized=0, exit_reason='d1_onesell_locked_unsold'）。

        baostock bars 须经 KlineCacheBarsProvider（enrich_pctchg S204 T1, pctChg 已补）。

        Returns (exit_price | None, exit_date_str | None, info_dict)。
        info_dict: optimism_flag / arm_path / d1_locked_days / naive_d1_open / unlock_date(可空)。
        """
        from engine.bar_utils import is_onesell_locked_next_bar  # noqa: PLC0415

        d1_idx = d_idx + 1
        open_d1 = float(bars[d1_idx].get("open", 0) or 0)
        info: dict = {
            "naive_d1_open": round(open_d1, 4),
            "d1_locked_days": 0,
            "unlock_date": None,
        }
        # 正常：D+1 非一字跌停 → open[D+1] 可卖（backward compat 原 overnight gap 口径）
        if not is_onesell_locked_next_bar(bars[d1_idx], code=code):
            info["optimism_flag"] = "s211_overnight_gap_regime_stratified"
            info["arm_path"] = "overnight_gap"
            return open_d1, str(bars[d1_idx].get("date", ""))[:10], info

        # D+1 一字跌停封死 → 找限跌打开日（首个非一字跌停且 open>0 的 bar）
        unlock_idx = None
        for j in range(d1_idx + 1, len(bars)):
            if is_onesell_locked_next_bar(bars[j], code=code):
                continue
            open_j = float(bars[j].get("open", 0) or 0)
            if open_j > 0:
                unlock_idx = j
                break
        if unlock_idx is None:
            # 一直封死到 cache 末 → 卖不掉, 诚实记 None（不臆造价）
            info["optimism_flag"] = "d1_onesell_locked_unsold"
            info["arm_path"] = "locked_unsold"
            info["d1_locked_days"] = len(bars) - 1 - d_idx
            return None, None, info
        # 限跌打开日 open 可卖
        open_unlock = float(bars[unlock_idx].get("open", 0) or 0)
        info["optimism_flag"] = "d1_onesell_locked_resold_at_unlock"
        info["arm_path"] = "locked_gap_unlocked"
        info["d1_locked_days"] = unlock_idx - d1_idx
        info["unlock_date"] = str(bars[unlock_idx].get("date", ""))[:10]
        return open_unlock, str(bars[unlock_idx].get("date", ""))[:10], info

    def settle_pending_consecutive_relay(self) -> dict:
        """S211 — 重算昨日未平 consecutive_relay 'hold' / 'd1_onesell_locked_unsold' 记录。

        overnight gap path 需 D+1 bar（exit=open[D+1] 或限跌打开日 open）。_process 当日跑时
        D+1 缺 → 'hold' is_realized=0；D+1 一字跌停封死且限跌未打开 → 'd1_onesell_locked_unsold'
        is_realized=0。次日 bars 增长后此方法重算：query is_realized=0 → _resolve_gap_exit
        找 exit（D+1 非封死用 open[D+1], 封死用限跌打开日 open）→ gap_net_return →
        update_settlement_v2 标 realized。

        realizability-bias 修（2026-09-19）：原 naive 用 open[D+1] 算 gap，D+1 一字跌停时
        locked 价卖不掉 → 现走 _resolve_gap_exit 找限跌打开日 open 重算。
        """
        pending = self._journal.query_records(arm="consecutive_relay", is_realized=0, is_dead_arm=0)
        # settle 'hold'（D+1 bar 缺）+ 'd1_onesell_locked_unsold'（限跌未打开, cache 增长后可能已打开）
        holds = [r for r in pending if r.exit_reason in ("hold", "d1_onesell_locked_unsold")]
        n_settled = 0
        for pos in holds:
            bars = self._bars_provider(pos.stock_code)
            if not bars:
                continue
            d_idx = next(
                (i for i, b in enumerate(bars)
                 if str(b.get("date", ""))[:10] == pos.entry_date),
                None,
            )
            if d_idx is None or d_idx + 1 >= len(bars):
                continue  # D+1 bar 仍缺
            close_d = float(bars[d_idx].get("close", 0) or 0)
            if close_d <= 0:
                continue
            entry_price = float(pos.entry_price) if pos.entry_price else close_d
            exit_price, exit_date, info = self._resolve_gap_exit(bars, d_idx, pos.stock_code)
            if exit_price is None or exit_price <= 0:
                # 限跌仍封死到 cache 末 → 仍卖不掉, 留 is_realized=0（等更多 bars 到达）
                continue
            regime = self._regime_for_date(pos.entry_date)
            size = self._arm_size("consecutive_relay", regime=regime)
            net_ratio, cost_pct, gross_ratio = gap_net_return(
                entry_price, exit_price, entry_date=pos.entry_date, size=size,
            )
            position_notional = entry_price * size
            net_pnl = net_ratio * position_notional
            exit_reason = "overnight_gap" if info["arm_path"] == "overnight_gap" else "locked_gap_unlocked"
            updated = self._journal.update_settlement_v2(
                signal_id=pos.signal_id,
                gross_return_v2=round(gross_ratio * 100, 4),
                exit_price=exit_price,
                exit_date=exit_date,
                exit_reason=exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=cost_pct,
                exit_model_version=(
                    "s211_overnight_gap" if exit_reason == "overnight_gap"
                    else "s211_locked_gap_unlocked"
                ),
            )
            if updated:
                n_settled += 1
        return {"n_pending": len(holds), "n_settled": n_settled}

    def _process_consecutive_relay(self, target_date: str) -> dict:
        """S211 consecutive_relay 臂（overnight gap path，regime-stratified §44 cap）。

        1. scan_consecutive_relay(target_date) → lbc>=2 picks（zt_history T-1=signal date）
        2. per pick: bars 找 D_idx（target_date）+ D+1 bar
        3. D 日一字板 filter（_is_unbuyable_next_bar(bars[D_idx])，入场日 close 买不到）
        4. D+1 bar 缺 → 'hold' is_realized=0（settle_pending 次日重算）
        5. _resolve_gap_exit: D+1 非一字跌停用 open[D+1]；D+1 一字跌停封死找限跌打开日
           open（realizability-bias 修, naive D+1 open 卖不掉）；封死到末 → None 卖不掉
        6. gap_net_return(close[D], exit_price) → (net_ratio, cost_pct, gross_ratio)
        7. net_pnl = net_ratio × position_notional；size = _arm_size(regime)（§44 cap bite）
        8. trade_journal.insert(is_realized=1)；locked 未打开 → is_realized=0 'd1_onesell_locked_unsold'

        与 _process_post_first_board 区别：overnight gap path（非 -4/+8/3 path_return），
        entry=D 日 close（非 T+1 open），exit=D+1 open（1 天强制平，无 stop/take）。
        """
        from pre_limitup_scanner import scan_consecutive_relay  # noqa: PLC0415
        from strategies.kline_returns import _is_unbuyable_next_bar  # noqa: PLC0415

        candidates = scan_consecutive_relay(target_date, previous_trade_day=target_date)
        n_unbuyable = 0
        n_buyable = 0
        n_realized = 0

        for cand in candidates:
            code = cand.get("code") or ""
            if not code:
                continue
            bars = self._bars_provider(code)
            if not bars:
                continue

            d_idx = next(
                (i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == target_date),
                None,
            )
            if d_idx is None:
                continue  # 无 D 日 bar
            close_d = float(bars[d_idx].get("close", 0) or 0)
            if d_idx + 1 >= len(bars):
                # D+1 bar 缺（T+1 guard）→ 'hold' is_realized=0
                # entry_price=close_d（D 日 bar 已有，settle 时 exit=open[D+1] 补）
                record = JournalRecord.create(
                    arm="consecutive_relay", stock_code=code,
                    entry_price=close_d if close_d > 0 else None,
                    entry_date=target_date,
                    exit_reason="hold", is_realized=0,
                    fills_json=json.dumps({
                        "optimism_flag": "d1_bar_missing_t1_guard",
                        "lbc": cand.get("lbc"),
                    }),
                )
                self._journal.insert(record)
                continue

            # M5 财报季拉黑（DANGER_MONTHS 未披露 → 一字跌停风险，跳过交易）
            from routers.earnings_calendar import is_earnings_season_unsafe  # noqa: PLC0415
            if is_earnings_season_unsafe(code, target_date):
                record = JournalRecord.create(
                    arm="consecutive_relay", stock_code=code,
                    entry_price=None, entry_date=target_date,
                    exit_reason="earnings_season_blacklist", is_realized=1,
                    fills_json=json.dumps({
                        "blacklist_reason": "earnings_season_undisclosed",
                        "lbc": cand.get("lbc"),
                    }),
                )
                self._journal.insert(record)
                n_unbuyable += 1
                continue

            # D 日一字板 filter（入场日 close 买不到，survivorship 过滤）
            if _is_unbuyable_next_bar(bars[d_idx], code=code):
                record = JournalRecord.create(
                    arm="consecutive_relay", stock_code=code,
                    entry_price=None, entry_date=target_date,
                    exit_reason="unbuyable", is_realized=1,
                    fills_json=json.dumps({
                        "fill_reason": "d_day_unbuyable_一字板",
                        "lbc": cand.get("lbc"),
                    }),
                )
                self._journal.insert(record)
                n_unbuyable += 1
                continue

            # realizability-bias 修：D+1 一字跌停封死时找限跌打开日 open（非 naive D+1 open）
            exit_price, exit_date, info = self._resolve_gap_exit(bars, d_idx, code)
            if exit_price is None:
                # D+1 一字跌停封死且限跌未打开（到 cache 末仍 locked）→ 卖不掉, 诚实记 None
                # is_realized=0（settle 次日 cache 增长后若打开则 re-settle at 打开日 open）
                record = JournalRecord.create(
                    arm="consecutive_relay", stock_code=code,
                    entry_price=close_d if close_d > 0 else None,
                    entry_date=target_date,
                    exit_reason="d1_onesell_locked_unsold", is_realized=0,
                    fills_json=json.dumps({**info, "lbc": cand.get("lbc")}),
                )
                self._journal.insert(record)
                continue
            if close_d <= 0 or exit_price <= 0:
                continue

            regime = self._regime_for_date(target_date)
            size = self._arm_size("consecutive_relay", regime=regime)
            net_ratio, cost_pct, gross_ratio = gap_net_return(
                close_d, exit_price, entry_date=target_date, size=size,
            )
            position_notional = close_d * size
            net_pnl = net_ratio * position_notional
            exit_reason = "overnight_gap" if info["arm_path"] == "overnight_gap" else "locked_gap_unlocked"

            record = JournalRecord.create(
                arm="consecutive_relay", stock_code=code,
                entry_price=close_d, entry_date=target_date,
                exit_price=exit_price,
                exit_date=exit_date,
                exit_reason=exit_reason,
                net_pnl=round(net_pnl, 2),
                cost_pct=cost_pct,
                gross_return=round(gross_ratio * 100, 4),
                is_realized=1,
                fills_json=json.dumps({
                    "net_ratio": round(net_ratio, 6),
                    "gross_ratio": round(gross_ratio, 6),
                    "cost_pct": cost_pct,
                    "position_notional": round(position_notional, 2),
                    "regime": regime,
                    "lbc": cand.get("lbc"),
                    **info,
                }),
            )
            self._journal.insert(record)
            n_buyable += 1
            n_realized += 1

        return {
            "n_candidates": len(candidates),
            "n_buyable": n_buyable,
            "n_unbuyable": n_unbuyable,
            "n_realized": n_realized,
        }

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

            size = self._arm_size("breakout")
            trades = Trades(
                code=cand.code,
                signal_date=target_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=size,
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

            position_notional = float(filled.entry_price) * size
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
                    "optimism_flag": "gap_through_modeled_v2",
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

    # ── S209 T10 post_first_board 臂（探索性 PAPER，仿 _process_breakout 换 scan_pre_limitup）──

    def _process_post_first_board(self, target_date: str) -> dict:
        """post_first_board 臂（S209 探索性 PAPER）：scan_pre_limitup → Trades → execute → path_return。

        仿 _process_breakout，仅 signal 生成器不同：scan_pre_limitup(target_date, previous_trade_day=target_date)
        → lbc==1 首板 on target_date（zt_history T-1=signal date）。fill T1OpenFill（target_date+1 open）。
        -4/+8/3 冻结（继承 breakout 74295b9，不新 sweep）。is_unbuyable 过滤（一字板封死 survivorship）。
        前提证伪（breakout +0.36% net 是 5元佣金门+regime 假象）→ exploratory 自证，lift_mult=0.5。
        """
        from pre_limitup_scanner import scan_pre_limitup  # noqa: PLC0415

        # 首板 on target_date（signal date = previous_trade_day = target_date）
        candidates = scan_pre_limitup(target_date, previous_trade_day=target_date)
        n_unbuyable = 0
        n_buyable = 0
        n_realized = 0

        for cand in candidates:
            bars = self._bars_provider(cand["code"])
            if not bars:
                continue

            size = self._arm_size("post_first_board")
            trades = Trades(
                code=cand["code"],
                signal_date=target_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=size,
            )
            filled = self._executor.execute(trades, bars, T1OpenFill())

            if not filled.is_accepted():
                # survivorship 过滤：一字板封死买不到
                record = JournalRecord.create(
                    arm="post_first_board", stock_code=cand["code"],
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
                stop_pct=POST_FIRST_BOARD_STOP_PCT,
                take_profit_pct=POST_FIRST_BOARD_TAKE_PCT,
                max_hold_days=POST_FIRST_BOARD_MAX_HOLD,
                apply_cost=True,
            )
            if pr is None:
                # T+1 guard 或数据不足 → 仍录 entry，标 unrealized 'hold'
                record = JournalRecord.create(
                    arm="post_first_board", stock_code=cand["code"],
                    entry_price=filled.entry_price, entry_date=target_date,
                    exit_reason="hold", is_realized=0,
                    fills_json=json.dumps({
                        "fill_status": filled.fill_status,
                        "optimism_flag": "path_return_none_t1_guard",
                    }),
                )
                self._journal.insert(record)
                continue

            position_notional = float(filled.entry_price) * size
            net_pnl = pr.return_pct / 100.0 * position_notional

            record = JournalRecord.create(
                arm="post_first_board", stock_code=cand["code"],
                entry_price=filled.entry_price, entry_date=target_date,
                exit_price=pr.exit_price,
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
                    "optimism_flag": "exploratory_paper_gap_through_modeled_v2",
                    "raw_exit_reason": pr.exit_reason,
                    "position_notional": round(position_notional, 2),
                    "lbc": cand.get("lbc"),
                    "zt_count_today": cand.get("zt_count_today"),
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

            size = self._arm_size("trend")
            trades = Trades(
                code=code,
                signal_date=target_date,
                fill_type=FILL_T_PLUS_1_OPEN,
                direction="long",
                size=size,
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

            position_notional = float(filled.entry_price) * size
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
                    "optimism_flag": "gap_through_modeled_v2",
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
