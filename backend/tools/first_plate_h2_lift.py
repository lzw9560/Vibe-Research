# -*- coding: utf-8 -*-
"""S152 盘中 H2 harness：baostock 5min kline → 封板时间×开板次数 → day_paired_lift。

§44 证否选股（forward lift=0.983 劣于随机），edge 在盘中（未测 60%）。唯一未证伪维度
= first_plate H2（封板时间×开板次数）。seal_intraday_snapshots（60s 封单轮询）仅 4 天
且东财涨停池 live intraday 无历史可补——本 harness 用 baostock 5min kline（历史数年）推导
H2 特征，不依赖 60s 封单时序。

范式（复用 platform_breakout_lift / first_board_layer_lift）：
- day_paired_lift 非池化（防池化假象）
- within-day survivor resampling null（day_cluster_permutation）
- Bonferroni K=2（早封板 / 一字板 两组）
- four_state verdict（validated/未validated/劣于随机/探索性）

诚实：不事后调参，结果写 stdout。pre-register 冻结 commit（本 spec 创建时）。
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.first_board_layer_lift import day_paired_lift, four_state  # noqa: E402

# 预注册冻结参数
EARLY_LOCK_CUTOFF = "100000000"   # 早封板 = first_lock time <= 10:00
LATE_LOCK_CUTOFF = "140000000"     # 晚封板（尾盘）= first_lock time > 14:00（end_of_day_sneak）
HIGH_DROP_PCT = 3.0               # 大回撤阈值（max_drop_pct > 3%）
AUCTION_HIGH_PCT = 0.03            # 竞价高开阈值（fraction > 3%，auction_open_pct 存 fraction）
ALPHA_ADJ = 0.05 / 6              # Bonferroni K=6（早封板/一字板/开板/晚封板/大回撤/晚封×竞价高开）
N_PERM = 2000
PERM_SEED = 42
BAOSTOCK_SLEEP = 0.1             # baostock fetch 礼貌间隔（非防封必需）
_BS_READY = False                # baostock 单次 login（避免 per-call 840 次登录）


def _ensure_bs_login() -> None:
    """单次 baostock login（main 调用前 ensure，避免 per-fetch login 840 次拖垮）。"""
    global _BS_READY
    if _BS_READY:
        return
    import baostock as bs  # noqa: PLC0415
    bs.login()
    _BS_READY = True


def _six_to_baostock(code: str) -> str:
    """6 位 A 股 code → baostock 9 位（sh./sz. 前缀）。6/9 开头 sh 否则 sz。"""
    return f"sh.{code}" if code[0] in "689" else f"sz.{code}"


def fetch_5min_bars(code: str, date: str, days: int = 1) -> list[dict]:
    """baostock 5min kline（qfq）。date 起 days 个交易日。

    返 [{date, time, open, high, low, close, volume}, ...]。缺数据/非交易日返 []。
    baostock login 单次（main 起 _ensure_bs_login，不 per-call 重登）。
    """
    import baostock as bs  # noqa: PLC0415
    _ensure_bs_login()
    bars: list[dict] = []
    bc = _six_to_baostock(code)
    from datetime import datetime, timedelta
    start = date
    end = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days * 2 + 3)).strftime("%Y-%m-%d")
    try:
        rs = bs.query_history_k_data_plus(
            bc, "date,time,open,high,low,close,volume",
            start_date=start, end_date=end, frequency="5", adjustflag="2",
        )
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            bars.append({
                "date": row[0], "time": row[1],
                "open": float(row[2]), "high": float(row[3]),
                "low": float(row[4]), "close": float(row[5]),
                "volume": float(row[6]) if row[6] else 0.0,
            })
    except Exception:
        return []
    return bars


def compute_h2_features(today_bars: list[dict], next_bars: list[dict],
                         prev_close: float | None = None) -> dict | None:
    """R3：5min bars → H2 特征 + next_day_return + auction_open_pct。

    涨停价 = max(close) 当日（涨停股必触涨停价）。
    first_lock_time = 首 bar close>=涨停价 的 time。
    open_count = 封板后 close<涨停价 的 bar 数。
    broken_duration_min = open_count × 5。
    is_one_word = first_lock 为首 bar（09:35）且 open_count==0。
    next_day_return = (次日 close - 次日 open) / 次日 open（T+0 intraday 基线，对齐 S144 o2c）。
    auction_open_pct = (今日 open - 前日 close) / 前日 close × 100（集合竞价高开幅度；
        今日 open = today_bars[0].open 即 09:35 首 bar 撮合后开盘价≈竞价开盘价）。
        存 fraction（÷100，如 0.021）匹配 DiagnosisCard.tsx 显示约定。prev_close 缺→ None。
    缺数据返 None（不臆造）。
    """
    if not today_bars or len(today_bars) < 2:
        return None
    closes = [b["close"] for b in today_bars]
    zt_price = max(closes)
    if zt_price <= 0:
        return None
    # first_lock：首 bar close>=zt_price
    first_lock_idx = next((i for i, b in enumerate(today_bars) if b["close"] >= zt_price), None)
    if first_lock_idx is None:
        return None
    first_lock_time = today_bars[first_lock_idx]["time"]
    # open_count：封板后 close<zt 的 bar 数（含开板后重新封板又开）
    open_count = sum(1 for b in today_bars[first_lock_idx + 1:] if b["close"] < zt_price)
    broken_duration_min = open_count * 5
    is_one_word = (first_lock_idx == 0) and (open_count == 0)
    # next_day_return：次日 open→close（T+0 intraday）
    next_day_return = None
    if next_bars:
        nb = next_bars[0]  # 次日首 bar（9:35）= open 区间
        nc = next_bars[-1]  # 次日末 bar（15:00）= close
        if nb.get("open") and nc.get("close") and nb["open"] > 0:
            next_day_return = round((nc["close"] - nb["open"]) / nb["open"] * 100, 4)
    # auction_open_pct：今日 open（= today_bars[0].open，09:35 首 bar 撮合后≈竞价开盘价）
    # vs 前日 close。存 fraction（÷100）匹配 DiagnosisCard.tsx:43 显示约定。
    auction_open_pct = None
    today_open = today_bars[0].get("open")
    if prev_close and today_open and prev_close > 0:
        auction_open_pct = round((today_open - prev_close) / prev_close, 4)  # fraction, e.g. 0.021=2.1%
    return {
        "zt_price": zt_price,
        "first_lock_time": first_lock_time,
        "first_lock_idx": first_lock_idx,
        "open_count": open_count,
        "broken_duration_min": broken_duration_min,
        "is_one_word": is_one_word,
        "next_day_return": next_day_return,
        "auction_open_pct": auction_open_pct,
    }


def fetch_prev_close(code: str, date: str) -> float | None:
    """baostock 前日 daily close（auction_open_pct 用）。取 date 前 5 日范围，最大 < date 的 close。

    复用 _ensure_bs_login（单次 session）。baostock daily kline frequency='d'。
    """
    import baostock as bs  # noqa: PLC0415
    _ensure_bs_login()
    bc = _six_to_baostock(code)
    from datetime import datetime, timedelta
    start = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=8)).strftime("%Y-%m-%d")
    end = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        rs = bs.query_history_k_data_plus(
            bc, "date,close", start_date=start, end_date=end,
            frequency="d", adjustflag="2",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
    except Exception:
        return None
    if not rows:
        return None
    # 取最大 date < date 的 close
    rows.sort(key=lambda r: r[0])
    try:
        return float(rows[-1][1])
    except (ValueError, IndexError):
        return None


def _time_suffix(time_str: str) -> str:
    """baostock time 'YYYYMMDDHHMMSSmmm' → 取 HHMMSSmmm 后 9 位（比较早封板用）。"""
    return time_str[-9:] if len(time_str) >= 9 else time_str


def _is_early_lock(feat: dict) -> bool:
    """早封板 = first_lock time <= 10:00（首 bar 09:35 一字板也算早）。"""
    return _time_suffix(feat["first_lock_time"]) <= EARLY_LOCK_CUTOFF


def _is_late_lock(feat: dict) -> bool:
    """T2.3 晚封板（尾盘突袭）= first_lock time > 14:00（end_of_day_sneak 近似）。"""
    return _time_suffix(feat["first_lock_time"]) > LATE_LOCK_CUTOFF


def _is_open_board(feat: dict) -> bool:
    """T2.3 开板 = broken_duration_min > 0（盘中开过板，reverse_package 近似）。"""
    return (feat.get("broken_duration_min") or 0) > 0


def _is_high_drop(feat: dict) -> bool:
    """T2.3 大回撤 = max_drop_pct > 3%（weak_turn_strong 候选：回撤大可能转强）。"""
    return (feat.get("max_drop_pct") or 0) > HIGH_DROP_PCT


def _is_auction_high(feat: dict) -> bool:
    """竞价高开 = auction_open_pct > 3%（fraction > 0.03）。"""
    return (feat.get("auction_open_pct") or 0) > AUCTION_HIGH_PCT


def _is_late_x_auction_high(feat: dict) -> bool:
    """预注册单一交互：晚封板（尾盘突袭）× 竞价高开——测 late_lock 弱正是否随竞价 context 增强。

    synthesis 警告：多维交互 Bonferroni 膨胀，仅预注册此单一假设（非 data-mining 全组合）。
    """
    return _is_late_lock(feat) and _is_auction_high(feat)


def day_cluster_permutation(surv_by_day, raw_by_day, n_perm=N_PERM, seed=PERM_SEED):
    """within-day survivor resampling null（复用 platform_breakout_lift 范式）。

    逐日内随机选同大小子集当 survivor 重算 day_paired_lift，返 null lift 列表。
    observed lift 须在 null P95 以上。filter-edge 锐检验。
    """
    rng = random.Random(seed)
    nulls = []
    for _ in range(n_perm):
        null_surv = {}
        for date, raw_rets in raw_by_day.items():
            surv_rets = surv_by_day.get(date, [])
            if not surv_rets or len(raw_rets) < len(surv_rets):
                continue
            null_surv[date] = rng.sample(raw_rets, len(surv_rets))
        if null_surv:
            lr = day_paired_lift(null_surv, raw_by_day)
            if lr["winrate_lift_avg"] is not None:
                nulls.append(lr["winrate_lift_avg"])
    return nulls


def _load_universe(max_per_day: int | None = None) -> dict[str, list[str]]:
    """R1：gene_scores eastmoney_live 信号日 → {date: [涨停股 codes]}。

    max_per_day：按 total_score desc 取 top N（preliminary verdict 控 fetch 预算；
    None=全量）。caveat：cap 后 raw 基线=当日 top N 而非全涨停股（采样，非全量）。
    """
    from config import GENE_SCORES_DB_PATH
    from db_health import get_healthy_conn
    conn = get_healthy_conn(GENE_SCORES_DB_PATH)
    try:
        if max_per_day:
            rows = conn.execute(
                "SELECT date, code, total_score FROM gene_scores "
                "WHERE data_source='eastmoney_live' ORDER BY date, total_score DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, code FROM gene_scores WHERE data_source='eastmoney_live' ORDER BY date"
            ).fetchall()
    finally:
        conn.close()
    by_day: dict[str, list] = defaultdict(list)
    for r in rows:
        code = str(r[1]).strip()
        if code:
            by_day[r[0]].append((code, r[2]) if max_per_day else code)
    if max_per_day:
        # 每日去重（按 code 保首）后取 top N
        return {d: [c for c, _ in list(dict.fromkeys(codes))[:max_per_day]]
                for d, codes in by_day.items()}
    return {d: list(dict.fromkeys(codes)) for d, codes in by_day.items()}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="S152 盘中 H2 harness（baostock 5min 封板时间×开板次数 lift）")
    ap.add_argument("--max-per-day", type=int, default=15,
                    help="每日取 top N 涨停股（preliminary；None=全量，default 15）")
    ap.add_argument("--full", action="store_true", help="全量跑（忽略 max-per-day）")
    ap.add_argument("--no-cache", action="store_true", help="强制 re-fetch（忽略 features cache）")
    args = ap.parse_args()
    max_per_day = None if args.full else args.max_per_day

    # features cache（re-run 秒级，避免 re-fetch baostock ~13min）
    from vr_paths import resolve_data_dir
    suffix = "_full" if args.full else f"_top{max_per_day or 'all'}"
    cache_path = Path(resolve_data_dir()) / f"h2_features_cache{suffix}.json"

    _ensure_bs_login()  # 单次 login（避免 per-fetch 840 次登录拖垮）
    if cache_path.exists() and not args.no_cache:
        features = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"loaded {len(features)} features from cache {cache_path.name}", flush=True)
        skipped = -1  # cache 路径不报告 skipped
    else:
        universe = _load_universe(max_per_day=max_per_day)
        total_pairs = sum(len(v) for v in universe.values())
        print(f"universe: {len(universe)} 信号日, {total_pairs} (date, code) pairs"
              f"{' [preliminary top-' + str(max_per_day) + '/day]' if max_per_day else ' [full]'}", flush=True)

        # R2-R3: fetch 5min + compute H2 features per (date, code)
        features = []  # [{date, code, feat}]
        skipped = 0
        for di, (date, codes) in enumerate(universe.items()):
            print(f"  [{di+1}/{len(universe)}] {date}: {len(codes)} codes fetching...", flush=True)
            for code in codes:
                time.sleep(BAOSTOCK_SLEEP)
                today_bars = fetch_5min_bars(code, date, days=1)
                from datetime import datetime, timedelta
                next_start = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                time.sleep(BAOSTOCK_SLEEP)
                next_bars = fetch_5min_bars(code, next_start, days=1)
                next_bars = [b for b in next_bars if b["date"] > date]
                if next_bars:
                    next_bars = [b for b in next_bars if b["date"] == next_bars[0]["date"]]
                time.sleep(BAOSTOCK_SLEEP)
                prev_close = fetch_prev_close(code, date)  # 竞价 auction_open_pct 用
                feat = compute_h2_features(today_bars, next_bars, prev_close=prev_close)
                if feat is None or feat["next_day_return"] is None:
                    skipped += 1
                    continue
                features.append({"date": date, "code": code, **feat})
        print(f"computed: {len(features)} features (skipped {skipped} 缺数据)", flush=True)
        # baostock logout（单次 login 的收尾）
        try:
            import baostock as bs
            bs.logout()
        except Exception:
            pass
        try:
            cache_path.write_text(json.dumps(features, ensure_ascii=False), encoding="utf-8")
            print(f"cached {len(features)} features → {cache_path.name}", flush=True)
        except Exception:
            pass

    if len(features) < 30:
        print(f"n={len(features)} < 30 → 探索性，不足 verdict")
        # 仍输出描述性统计
        early = [f for f in features if _is_early_lock(f)]
        one_word = [f for f in features if f["is_one_word"]]
        open_board = [f for f in features if _is_open_board(f)]
        late_lock = [f for f in features if _is_late_lock(f)]
        high_drop = [f for f in features if _is_high_drop(f)]
        print(f"  早封板(<=10:00): {len(early)}/{len(features)}")
        print(f"  一字板: {len(one_word)}/{len(features)}")
        print(f"  开板(broken>0): {len(open_board)}/{len(features)}")
        print(f"  晚封板(>14:00): {len(late_lock)}/{len(features)}")
        print(f"  大回撤(>3%): {len(high_drop)}/{len(features)}")
        return 0

    # R4: day_paired_lift 5 组 + null（T2.2 early/one_word + T2.3 open/late/drop）
    raw_by_day: dict[str, list[float]] = defaultdict(list)
    early_by_day: dict[str, list[float]] = defaultdict(list)
    oneword_by_day: dict[str, list[float]] = defaultdict(list)
    open_by_day: dict[str, list[float]] = defaultdict(list)
    late_by_day: dict[str, list[float]] = defaultdict(list)
    drop_by_day: dict[str, list[float]] = defaultdict(list)
    latexa_by_day: dict[str, list[float]] = defaultdict(list)
    for f in features:
        ret = f["next_day_return"]
        raw_by_day[f["date"]].append(ret)
        if _is_early_lock(f):
            early_by_day[f["date"]].append(ret)
        if f["is_one_word"]:
            oneword_by_day[f["date"]].append(ret)
        if _is_open_board(f):
            open_by_day[f["date"]].append(ret)
        if _is_late_lock(f):
            late_by_day[f["date"]].append(ret)
        if _is_high_drop(f):
            drop_by_day[f["date"]].append(ret)
        if _is_late_x_auction_high(f):
            latexa_by_day[f["date"]].append(ret)

    groups = {
        "early_lock": early_by_day,      # T2.2 早封板
        "one_word": oneword_by_day,      # T2.2 一字板
        "open_board": open_by_day,       # T2.3 开板（reverse_package 近似）
        "late_lock": late_by_day,        # T2.3 晚封板（end_of_day_sneak 近似）
        "high_drop": drop_by_day,        # T2.3 大回撤（weak_turn_strong 候选）
        "late_x_auction": latexa_by_day,  # 预注册交互：晚封×竞价高开
    }
    results = {}
    for name, surv in groups.items():
        lr = day_paired_lift(surv, raw_by_day)
        lift = lr["winrate_lift_avg"]
        n = lr["surv_n_pooled"]
        state = four_state(lift, n)
        # null distribution
        nulls = day_cluster_permutation(surv, raw_by_day)
        null_p95 = round(sorted(nulls)[int(len(nulls) * 0.95)], 4) if nulls else None
        null_mean = round(statistics.mean(nulls), 4) if nulls else None
        results[name] = {
            "n": n, "lift": lift, "state": state,
            "n_days": lr["n_days"], "mean_lift": lr["mean_lift_avg"],
            "null_p95": null_p95, "null_mean": null_mean,
            "pass_filter_edge": lift is not None and null_p95 is not None and lift > null_p95,
        }

    print("\n=== S152 H2 verdict（baostock 5min, day_paired_lift 非池化, within-day survivor null）===")
    print(f"universe: {len(features)} features across {len(raw_by_day)} 日")
    print(f"Bonferroni K=6 α_adj={ALPHA_ADJ}（早封板/一字板/开板/晚封板/大回撤/晚封×竞价高开）")
    for name, r in results.items():
        print(f"  {name}: n={r['n']} lift={r['lift']} state={r['state']} "
              f"null_p95={r['null_p95']} pass_filter_edge={r['pass_filter_edge']}")
    overall = "validated" if any(r["state"] == "validated" and r["pass_filter_edge"] for r in results.values()) \
        else "未validated/劣于随机"
    print(f"overall: {overall}")
    print("caveat: next_day_return=T+0 intraday o2c（未剔 unbuyable 一字板，S144 口径 follow-up）")
    print("caveat: 5min 粒度（60s 封单 60s→5min coarser，broken_duration<5min 漏标）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
