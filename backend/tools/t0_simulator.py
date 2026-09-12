# -*- coding: utf-8 -*-
"""S189 T4 · t0_simulator——对历史 breakout trades 模拟做 T，验证补成本 gap。

A 数据支撑（S188）：breakout D+1 gross+0.52% net-1.14%（成本~1.66% 吃正毛）。
本脚本对 trade_journal breakout trades，拉建仓日 mootdx tick → 算 OFI proxy
分钟序列 → 拐点策略 → 模拟 T+0 → 算 net vs 纯持有对比。

**S189 T4 grill 修订（2026-09-12，6 视角对抗审后）**：
- oracle 加 buy-first 镜像分支（两方向取 max）——原只 sell-first（捕回调），漏 rally；
  breakout D+1 上行日 rally 是主导 swing，sell-first-only 是 §44 v1 式假阴性。
- simulate_t0 加 buy-first 配对 pass + 先配对后截断（修截断 bug）。
- price 策略改因果窗口 [i-lookback, i]（去 i+lookback 前视）。
- t0_cost 用 T+0 专属滑点 T0_SLIPPAGE_PCT=0.10%（VWAP→execution shortfall，
  非 breakout 的 0.70% 理论价桥接）+ 佣金费率 max(notional×0.025%, 5元)。
- scope：仅测建仓日（D+1）单日 T+0；D+2..D+5 holding 期多日累计未测（输出标注）。

用法（需 ~/stoke venv；首次跑 populate cache，后续策略命中 cache 秒出）：
  cd ~/stoke && uv run python /abs/path/backend/tools/t0_simulator.py --output /tmp/t0_full.json
  cd ~/stoke && uv run python /abs/path/backend/tools/t0_simulator.py --compare --sizes 100,1000,10000 --output /tmp/t0_cmp.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vr_paths import resolve_data_dir  # noqa: E402
from engine.accounting import t0_cost  # noqa: E402
from engine.intraday_ofi import ofi_turn_points, is_auction_period  # noqa: E402

#: 分钟序列 cache 目录（私有数据，.vibe-research/ 下不进 git）。
SERIES_CACHE_DIR = resolve_data_dir() / "t0_cache"


def _load_breakout_trades(limit: int | None = None) -> list[dict]:
    """从 trade_journal 读 breakout trades（有 entry_date + entry_price + signal_id）。"""
    db = resolve_data_dir() / "trade_journal.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT signal_id, stock_code, entry_price, entry_date FROM trade_journal "
            "WHERE arm='breakout' AND entry_price IS NOT NULL AND entry_price > 0 "
            "ORDER BY entry_date",
        ).fetchall()
        if limit:
            rows = rows[:limit]
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _fetch_raw_ticks(code: str, date_compact: str) -> list[dict]:
    """直接调 mootdx Quotes.transactions 拉当日 raw 分笔（t0_simulator 在 stoke venv 跑有 mootdx）。"""
    try:
        from mootdx.quotes import Quotes  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
    except ImportError:
        return []
    q = Quotes.factory(market="std")
    all_ticks = []
    start = 0
    for _ in range(20):
        try:
            df = q.transactions(symbol=code, date=date_compact, start=start, offset=2000)
        except Exception:  # noqa: BLE001
            break
        if df is None or len(df) == 0:
            break
        all_ticks.append(df)
        if len(df) < 2000:
            break
        start += 2000
    if not all_ticks:
        return []
    df_all = pd.concat(all_ticks, ignore_index=True)
    return df_all.to_dict(orient="records")


def _ofi_proxy_minute_series(ticks: list[dict]) -> list[list]:
    """从分笔算分钟级 OFI proxy + 分钟 OHLC-ish + 主动买卖量。

    返 [[mm, ofi, vwap, high, low, vol, buy_vol, sell_vol], ...] 按时间排序。
    baseline 策略只读 index 1(ofi)/2(vwap)，与旧 [mm,ofi,vwap] 三元组兼容。
    """
    from collections import defaultdict  # noqa: PLC0415
    min_buy: dict[str, float] = defaultdict(float)
    min_sell: dict[str, float] = defaultdict(float)
    min_amount: dict[str, float] = defaultdict(float)
    min_vol: dict[str, float] = defaultdict(float)
    min_high: dict[str, float] = defaultdict(float)
    min_low: dict[str, float] = defaultdict(lambda: 1e18)
    for t in ticks:
        mm = str(t.get("time", ""))[:5]
        if is_auction_period(mm):
            continue
        vol = int(t.get("vol", 0))
        price = float(t.get("price", 0) or 0)
        bs = int(t.get("buyorsell", 0))
        if bs == 1:
            min_buy[mm] += vol
        elif bs == 2:
            min_sell[mm] += vol
        min_amount[mm] += price * vol
        min_vol[mm] += vol
        if price > 0:
            if price > min_high[mm]:
                min_high[mm] = price
            if price < min_low[mm]:
                min_low[mm] = price
    minutes = sorted(set(list(min_buy.keys()) + list(min_sell.keys()) + list(min_vol.keys())))
    series = []
    for mm in minutes:
        b, s = min_buy.get(mm, 0), min_sell.get(mm, 0)
        total = b + s
        ofi = (b - s) / total if total > 0 else 0.0
        v = min_vol.get(mm, 0)
        vwap = min_amount.get(mm, 0) / v if v > 0 else 0.0
        high = min_high.get(mm, 0.0)
        low = min_low.get(mm, 1e18)
        if low > 1e17:
            low = vwap
        series.append([mm, ofi, vwap, high, low, v, b, s])
    return series


def _series_cache_path(code: str, date_compact: str) -> Path:
    return SERIES_CACHE_DIR / f"{code}_{date_compact}.json"


def _load_or_fetch_ofi_series(code: str, date_compact: str) -> list[list]:
    """分钟序列 cache（首次跑 populate，后续命中 cache 秒出）。"""
    SERIES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _series_cache_path(code, date_compact)
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    ticks = _fetch_raw_ticks(code, date_compact)
    series = _ofi_proxy_minute_series(ticks)
    try:
        cache.write_text(json.dumps(series, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return series


# ─────────────────────────── 拐点策略族 ───────────────────────────
# 每个策略输入 ofi_series，输出 {"sell_points": [idx...], "buy_points": [idx...]}（idx 为分钟序号）。
# simulate_t0 做两方向配对：sell-first（卖点→其后买点，卖高买低捕回调）+ buy-first（买点→其后卖点，买低卖高捕 rally）。

def _strategy_baseline(ofi_series: list[list]) -> dict[str, list[int]]:
    """简单正负拐点（ofi_turn_points）。正转负=卖，负转正=买。两方向配对在 simulate_t0。"""
    ofi_vals = [x[1] for x in ofi_series]
    return ofi_turn_points(ofi_vals)


def _strategy_threshold(ofi_series: list[list], threshold: float = 0.15) -> dict[str, list[int]]:
    """OFI 幅值阈值拐点——过滤噪声：只在 OFI 越过 ±threshold 时注册拐点。"""
    sell_points: list[int] = []
    buy_points: list[int] = []
    for i in range(1, len(ofi_series)):
        prev, curr = ofi_series[i - 1][1], ofi_series[i][1]
        if prev >= threshold and curr < threshold:
            sell_points.append(i)
        elif prev <= -threshold and curr > -threshold:
            buy_points.append(i)
    return {"sell_points": sell_points, "buy_points": buy_points}


def _strategy_slope(ofi_series: list[list], window: int = 3, slope_min: float = 0.05) -> dict[str, list[int]]:
    """OFI 斜率拐点——d(OFI)/dt 变号 + 幅值。"""
    sell_points: list[int] = []
    buy_points: list[int] = []
    ofi_vals = [x[1] for x in ofi_series]
    prev_slope_pos = True
    for i in range(1, len(ofi_vals)):
        w = min(window, i)
        slope = ofi_vals[i] - ofi_vals[i - w]
        slope_pos = slope >= 0
        if abs(slope) >= slope_min:
            if prev_slope_pos and not slope_pos:
                sell_points.append(i)
            elif not prev_slope_pos and slope_pos:
                buy_points.append(i)
            prev_slope_pos = slope_pos
    return {"sell_points": sell_points, "buy_points": buy_points}


def _strategy_price_confirmed(ofi_series: list[list], lookback: int = 5) -> dict[str, list[int]]:
    """价格确认拐点——OFI 方向 + 分钟 VWAP **过去**局部极值（因果，无前视）。

    S189 grill 修订：原用 [i-lookback, i+lookback] 对称窗口（i+lookback 泄漏未来）+
    按检测分钟价成交（hindsight 膨胀）。改因果窗口 [i-lookback, i]（只看过去）——
    极值确认弱化但因果可达成；fill 仍用检测分钟 vwap（分钟收盘后触发，VWAP 是分钟均价）。
    """
    ofi_vals = [x[1] for x in ofi_series]
    vwaps = [x[2] for x in ofi_series]
    sell_points: list[int] = []
    buy_points: list[int] = []
    for i in range(1, len(ofi_vals)):
        prev, curr = ofi_vals[i - 1], ofi_vals[i]
        # 因果窗口 [i-lookback, i]：只看过去 lookback+1 分钟（含当前）
        lo = max(0, i - lookback)
        window_v = vwaps[lo:i + 1]
        if not window_v or vwaps[i] <= 0:
            continue
        is_local_high = vwaps[i] >= max(window_v)  # 当前是过去 lookback 分钟最高
        is_local_low = vwaps[i] <= min(window_v)
        if prev >= 0 and curr < 0 and is_local_high:
            sell_points.append(i)
        elif prev < 0 and curr >= 0 and is_local_low:
            buy_points.append(i)
    return {"sell_points": sell_points, "buy_points": buy_points}


def _strategy_oracle(ofi_series: list[list]) -> dict[str, list[int]]:
    """预言机上界——日内最优单 pair（**两方向取 max**，看未来不可实现，定天花板）。

    S189 grill 修订：原只 sell-first（卖较早高→买较晚低，价跌赚），漏 buy-first
    （买较早低→卖较晚高，价涨赚=rally）。breakout D+1 上行日 rally 主导，
    sell-first-only 是 §44 v1 式假阴性。现两方向各跑单遍取 spread 大者。

    直接用 ofi_series 索引（不过滤 vwaps，修索引错位 bug）。返 sell_points/buy_points，
    simulate_t0 两方向配对会捕（sell-first: sell<buy；buy-first: buy<sell 即 sell_points>buy_points）。
    """
    n = len(ofi_series)
    if n < 2:
        return {"sell_points": [], "buy_points": []}
    # sell-first: max(max_val[0..j-1] - vwap[j]) —— 卖较早高买较晚低
    sf = (-1, -1, -1e18)  # (sell_idx, buy_idx, spread)
    max_val = -1.0
    max_idx = -1
    for j in range(n):
        vj = ofi_series[j][2]
        if vj <= 0:
            continue
        if max_idx >= 0:
            sp = max_val - vj
            if sp > sf[2]:
                sf = (max_idx, j, sp)
        if vj > max_val:
            max_val = vj
            max_idx = j
    # buy-first: max(vwap[j] - min_val[0..j-1]) —— 买较早低卖较晚高（rally）
    bf = (-1, -1, -1e18)  # (buy_idx, sell_idx, spread)
    min_val = 1e18
    min_idx = -1
    for j in range(n):
        vj = ofi_series[j][2]
        if vj <= 0:
            continue
        if min_idx >= 0:
            sp = vj - min_val
            if sp > bf[2]:
                bf = (min_idx, j, sp)
        if vj < min_val:
            min_val = vj
            min_idx = j
    # 取两方向 spread 大者；buy-first 编码为 sell_points=[sell_later], buy_points=[buy_earlier]
    if sf[0] >= 0 and sf[2] >= bf[2]:
        return {"sell_points": [sf[0]], "buy_points": [sf[1]]}  # sell < buy
    if bf[0] >= 0:
        return {"sell_points": [bf[1]], "buy_points": [bf[0]]}  # buy < sell (sell_points > buy_points)
    return {"sell_points": [], "buy_points": []}


STRATEGIES = {
    "baseline": _strategy_baseline,
    "threshold": _strategy_threshold,
    "slope": _strategy_slope,
    "price": _strategy_price_confirmed,
    "oracle": _strategy_oracle,
}


def _pair_pnl(sell_price: float, buy_price: float, cost_pct: float) -> float:
    """单 T+0 pair 净收益（百分点 of notional）：(卖-买)/买×100 - cost。两方向通用。"""
    if buy_price <= 0:
        return 0.0
    return (sell_price - buy_price) / buy_price * 100 - cost_pct


def simulate_t0(
    trade: dict,
    strategy: str = "baseline",
    max_t0_per_day: int = 2,
    size: float = 100,
) -> dict:
    """对单笔 trade 模拟做 T（**两方向配对**）。返 {signal_id, n_t0_pairs, t0_pnl_pct, ...}。

    S189 grill 修订：
    - 两方向配对——sell-first（卖点→其后未用买点）+ buy-first（买点→其后未用卖点）。
      spec R1 两方向都合法（底仓 T+0）；breakout 上行日 rally 由 buy-first 捕。
    - 先全量配对再截断到 max_t0_per_day 个 pair（修"先截断后配对丢 pair"bug）。
    """
    code = trade["stock_code"]
    entry_price = float(trade["entry_price"] or 0)
    entry_date = trade["entry_date"]
    date_compact = entry_date.replace("-", "")
    sid = trade["signal_id"]
    if entry_price <= 0:
        return {"signal_id": sid, "code": code, "note": "entry_price 无"}

    ofi_series = _load_or_fetch_ofi_series(code, date_compact)
    if len(ofi_series) < 2:
        return {"signal_id": sid, "code": code, "note": "无分笔数据/OFI 序列不足"}

    strat_fn = STRATEGIES.get(strategy, _strategy_baseline)
    turn_points = strat_fn(ofi_series)
    sell_pts = turn_points["sell_points"]
    buy_pts = turn_points["buy_points"]

    t0_cost_pct = t0_cost(entry_price, size, entry_date)
    pairs: list[tuple[int, int]] = []  # (sell_idx, buy_idx)
    used_sell: set[int] = set()
    used_buy: set[int] = set()
    # sell-first: 每个卖点→其后第一个未用买点（卖高买低，捕回调）
    for sp in sell_pts:
        if len(pairs) >= max_t0_per_day:
            break
        bp = next((b for b in buy_pts if b > sp and b not in used_buy), None)
        if bp is not None:
            pairs.append((sp, bp))
            used_sell.add(sp)
            used_buy.add(bp)
    # buy-first: 每个买点→其后第一个未用卖点（买低卖高，捕 rally）
    for bp in buy_pts:
        if len(pairs) >= max_t0_per_day:
            break
        if bp in used_buy:
            continue
        sp = next((s for s in sell_pts if s > bp and s not in used_sell), None)
        if sp is not None:
            pairs.append((sp, bp))
            used_sell.add(sp)
            used_buy.add(bp)

    t0_pnl_pct = 0.0
    n_pairs = 0
    n_sellfirst = 0
    n_buyfirst = 0
    for sp, bp in pairs:
        sell_price = ofi_series[sp][2]
        buy_price = ofi_series[bp][2]
        t0_pnl_pct += _pair_pnl(sell_price, buy_price, t0_cost_pct)
        n_pairs += 1
        if bp > sp:
            n_sellfirst += 1
        else:
            n_buyfirst += 1

    return {
        "signal_id": sid,
        "code": code,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "n_minutes": len(ofi_series),
        "n_t0_opportunities": len(sell_pts) + len(buy_pts),
        "n_t0_pairs": n_pairs,
        "n_sellfirst_pairs": n_sellfirst,
        "n_buyfirst_pairs": n_buyfirst,
        "t0_pnl_pct": round(t0_pnl_pct, 3),
        "t0_cost_pct": round(t0_cost_pct, 3),
        "sell_points": len(sell_pts),
        "buy_points": len(buy_pts),
        "strategy": strategy,
        "size": size,
    }


def _summarize(results: list[dict], strategy: str, size: float) -> dict:
    valid = [r for r in results if "t0_pnl_pct" in r]
    n_with_data = len(valid)
    n_pairs_total = sum(r["n_t0_pairs"] for r in valid) if valid else 0
    n_buyfirst = sum(r.get("n_buyfirst_pairs", 0) for r in valid) if valid else 0
    n_sellfirst = sum(r.get("n_sellfirst_pairs", 0) for r in valid) if valid else 0
    total_t0_pnl = sum(r["t0_pnl_pct"] for r in valid) if valid else 0
    avg_t0_pnl = total_t0_pnl / n_with_data if n_with_data else 0
    helped = [r for r in valid if r["t0_pnl_pct"] > 0]
    hurt = [r for r in valid if r["t0_pnl_pct"] < 0]
    flat = [r for r in valid if r["t0_pnl_pct"] == 0]
    return {
        "strategy": strategy,
        "size": size,
        "total_trades": len(results),
        "valid": n_with_data,
        "n_pairs_total": n_pairs_total,
        "n_sellfirst_pairs": n_sellfirst,
        "n_buyfirst_pairs": n_buyfirst,
        "avg_t0_pnl_pct": round(avg_t0_pnl, 3),
        "total_t0_pnl_pct": round(total_t0_pnl, 3),
        "helped": len(helped),
        "hurt": len(hurt),
        "flat": len(flat),
        "helped_pct": round(len(helped) / n_with_data * 100, 1) if n_with_data else 0,
        "scope_caveat": "仅测建仓日(D+1)单日 T+0；D+2..D+5 holding 期多日累计未测；OFI proxy 非真五档",
    }


def main() -> None:
    p = argparse.ArgumentParser(description="S189 T4 · t0_simulator 做T模拟（两方向 + cache）")
    p.add_argument("--sample", type=int, default=None, help="抽样 N 笔")
    p.add_argument("--output", default=None, help="落盘 JSON（逐笔结果）")
    p.add_argument("--strategy", default="baseline", choices=list(STRATEGIES) + ["all"],
                   help="拐点策略（baseline/threshold/slope/price/oracle）")
    p.add_argument("--size", type=float, default=100, help="T+0 仓位（股，影响佣金占比）")
    p.add_argument("--compare", action="store_true", help="跑全策略对比（命中 cache 秒出）")
    p.add_argument("--sizes", default=None, help="comma-separated 仓位对比（如 100,1000,10000）")
    args = p.parse_args()

    trades = _load_breakout_trades(limit=args.sample)
    print(f"加载 breakout trades: {len(trades)} 笔", file=sys.stderr)

    if args.compare or args.strategy == "all":
        strategies = list(STRATEGIES)
    else:
        strategies = [args.strategy]

    sizes = [args.size]
    if args.sizes:
        sizes = [float(x) for x in args.sizes.split(",")]

    summary = {}
    for strat in strategies:
        for size in sizes:
            results = []
            for i, t in enumerate(trades):
                r = simulate_t0(t, strategy=strat, size=size)
                results.append(r)
                if (i + 1) % 50 == 0:
                    print(f"[{strat}/{size}] [{i+1}/{len(trades)}] 处理中...", file=sys.stderr)
            s = _summarize(results, strat, size)
            print(json.dumps(s, ensure_ascii=False), file=sys.stderr)
            summary[f"{strat}_{int(size)}"] = s
            if args.output and strat == strategies[0] and size == sizes[0]:
                Path(args.output).write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.output and args.compare:
        Path(args.output).write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
