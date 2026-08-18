# -*- coding: utf-8 -*-
"""S077 首板流剔除层 §44 lift 验证（B1）——逐层 day-paired lift。

验证 `specs/S075-首板流/grill-decisions.md` 硬剔除底线各层有没有 §44 edge。零风险研究。

**本轮交付 = 纯逻辑（逐层剔除 + 策略口径标的收益 + day-paired lift + 四态）+ 离线单测**。
live 主流程（em_zt_topic_pool 历史取数 + baostock kline + matrix 输出）下轮实现（见文件末 TODO）。

spec: `specs/S077-首板流剔除层lift验证/spec.md`

口径（KEY，避免 apples-to-oranges）：
- 策略标的收益 = (D+2 close - D+1 open)/D+1 open * 100（D=首板日；D+1=建仓日 open；D+2=卖出日 close）
  ≠ Phase 0 隔夜口径 (D+1 open - D close)/D close（`tools/first_board_premium_baseline.py`）
- day-paired lift：逐日 (存活 winrate/mean) vs (raw winrate/mean)，聚合非池化（防 day-cluster 假象，
  §44 已证池化 lift 是假象：grill-reframe 4.686x→day-cluster 1.723x）

grill-decisions.md 硬剔除（待 B1 验证后校准）：
- 层1 封板质量：炸板≥2 / 封单/流通市值<0.1%
- 层2 筹码结构：换手>30%
- 层3 市场环境：同板块涨停<2且无题材（孤板）；创业板**不剔除**（改分组展示，不进剔除）
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

# 直接执行时把 backend/ 加入 sys.path（tools. 包 + astock import 用；测试 import 时无害）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# grill-decisions.md 硬剔除阈值（待 B1 验证后校准——本脚本就是验它们的）
LAYER_THRESHOLDS: dict = {
    "max_break_times": 2,        # 层1：炸板次数 ≥2 剔除
    "min_seal_ratio": 0.001,     # 层1：封单/流通市值 <0.1% 剔除
    "max_turnover": 30.0,        # 层2：换手率 >30% 剔除
    "min_sector_zt_count": 2,   # 层3：同板块涨停 <2 且无题材（孤板）剔除
}

# 扣 0.4% 成本（佣金+滑点，弱近似，与 Phase 0 / first_board_settlement 一致）
COST_PCT: float = 0.4


# ─────────────────────────────────────────────────────────────────────────────
# 逐层剔除（纯函数，镜像 grill-decisions.md 硬剔除）
# ─────────────────────────────────────────────────────────────────────────────

def exclude_layer1_seal_quality(fb: dict, thresholds: dict | None = None) -> tuple[bool, str | None]:
    """层1 封板质量：炸板≥2 / 封单/流通市值<0.1%。

    返 (kept, reason)。数据缺失降级：字段 None 跳过对应条件（不因缺数误剔，宁可放过）。
    """
    th = thresholds or LAYER_THRESHOLDS
    reasons: list[str] = []
    bt = fb.get("break_times")
    if bt is not None and bt >= th["max_break_times"]:
        reasons.append(f"炸板{int(bt)}次")
    seal = fb.get("seal_amount")
    fcap = fb.get("float_cap")
    if seal is not None and fcap is not None and fcap > 0:
        ratio = seal / fcap
        if ratio < th["min_seal_ratio"]:
            reasons.append(f"封单/流通市值{ratio * 100:.2f}%")
    return (len(reasons) == 0, "/".join(reasons) if reasons else None)


def exclude_layer2_chip_structure(fb: dict, thresholds: dict | None = None) -> tuple[bool, str | None]:
    """层2 筹码结构：换手>30%。返 (kept, reason)。换手缺失→跳过（不误剔）。"""
    th = thresholds or LAYER_THRESHOLDS
    tp = fb.get("turnover_pct")
    if tp is not None and tp > th["max_turnover"]:
        return (False, f"换手{tp:.0f}%松动")
    return (True, None)


def exclude_layer3_market_env(fb: dict, thresholds: dict | None = None) -> tuple[bool, str | None]:
    """层3 市场环境：孤板（同板块涨停<2 且无题材）。

    创业板**不剔除**（grill-decisions.md 改分组展示，不进剔除路径；分组在 live main 标注）。
    """
    th = thresholds or LAYER_THRESHOLDS
    sector_count = fb.get("sector_zt_count", 0) or 0
    concept_tags = fb.get("concept_tags") or []
    if sector_count < th["min_sector_zt_count"] and not concept_tags:
        return (False, f"同板块{sector_count}家无题材(孤板)")
    return (True, None)


def apply_layers(first_boards: list[dict]) -> dict:
    """逐层剔除。

    返 {layer0/1/2/3: [codes], excluded: [{code, layer, reason}]}。
    layer0=全首板输入；layerN = 经层 N 剔除后存活（layer3 = 最终候选）。
    """
    layers: dict = {
        "layer0": [fb.get("code") for fb in first_boards],
        "excluded": [],
    }
    survivors = list(first_boards)
    for idx, fn in (
        (1, exclude_layer1_seal_quality),
        (2, exclude_layer2_chip_structure),
        (3, exclude_layer3_market_env),
    ):
        kept: list[dict] = []
        for fb in survivors:
            ok, reason = fn(fb)
            if ok:
                kept.append(fb)
            else:
                layers["excluded"].append({"code": fb.get("code"), "layer": idx, "reason": reason})
        survivors = kept
        layers[f"layer{idx}"] = [fb.get("code") for fb in survivors]
    return layers


# ─────────────────────────────────────────────────────────────────────────────
# 策略口径标的收益 + day-paired lift
# ─────────────────────────────────────────────────────────────────────────────

def target_return(d1_open: float | None, d2_close: float | None) -> float | None:
    """策略标的收益：(D+2 close - D+1 open)/D+1 open * 100。

    D=首板日；D+1=建仓日 open；D+2=卖出日 close。缺数据→None。
    与 `first_board_settlement.calc_target_return` 同口径（非 Phase 0 隔夜）。
    """
    if not d1_open or d1_open <= 0 or d2_close is None:
        return None
    return round((d2_close - d1_open) / d1_open * 100, 4)


def _winrate(returns: list[float]) -> float:
    """胜率 = 正收益占比。空→0。"""
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns)


def day_paired_lift(
    survivors_by_day: dict[str, list[float]],
    raw_by_day: dict[str, list[float]],
) -> dict:
    """逐日配对 lift（§44 day-cluster 防假象）。

    逐日算 (存活 winrate/mean) vs (raw winrate/mean)，再平均（**非池化**）——
    防存活股簇聚涨日把池化 lift 虚高（§44 已证此假象）。
    当日某侧空→跳（不可配对）。

    返 {n_days, day_lifts: [...], winrate_lift_avg, mean_lift_avg, surv_n_pooled, raw_n_pooled}。
    winrate_lift = 存活 winrate / raw winrate（§44 主口径）；mean_lift = 均值比（辅）。
    """
    day_lifts: list[dict] = []
    for date in sorted(set(survivors_by_day) | set(raw_by_day)):
        s = survivors_by_day.get(date, [])
        r = raw_by_day.get(date, [])
        if not s or not r:
            continue
        s_wr = _winrate(s)
        r_wr = _winrate(r)
        s_mean = statistics.mean(s)
        r_mean = statistics.mean(r)
        day_lifts.append({
            "date": date,
            "surv_n": len(s), "raw_n": len(r),
            "surv_winrate": round(s_wr, 4), "raw_winrate": round(r_wr, 4),
            "surv_mean": round(s_mean, 4), "raw_mean": round(r_mean, 4),
            "winrate_lift": round(s_wr / r_wr, 4) if r_wr > 0 else None,
            "mean_lift": round(s_mean / r_mean, 4) if r_mean != 0 else None,
        })
    wr_lifts = [d["winrate_lift"] for d in day_lifts if d["winrate_lift"] is not None]
    m_lifts = [d["mean_lift"] for d in day_lifts if d["mean_lift"] is not None]
    return {
        "n_days": len(day_lifts),
        "day_lifts": day_lifts,
        "winrate_lift_avg": round(statistics.mean(wr_lifts), 4) if wr_lifts else None,
        "mean_lift_avg": round(statistics.mean(m_lifts), 4) if m_lifts else None,
        "surv_n_pooled": sum(d["surv_n"] for d in day_lifts),
        "raw_n_pooled": sum(d["raw_n"] for d in day_lifts),
    }


def four_state(lift: float | None, n: int) -> str:
    """§44 四态（与 `first_board_settlement.judge_lift_four_states` 同口径）。

    n<30 探索性 / lift<1 劣于随机 / lift≥2 validated / 1≤lift<2 未validated。
    """
    if n < 30:
        return "探索性"
    if lift is None:
        return "探索性"
    if lift < 1.0:
        return "劣于随机"
    if lift >= 2.0:
        return "validated"
    return "未validated"


# ─────────────────────────────────────────────────────────────────────────────
# live 辅助（纯函数，可离线测）
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v) -> float | None:
    """raw 字段归一 float 或 None（东财 '-'/'null'/None/str 都收）。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_first_board(item: dict) -> bool:
    """东财 lbc=1 首板（lbc 缺失/0 也视为首板，与 Phase 0 一致）。"""
    lbc = item.get("lbc")
    return (str(lbc) == "1") or (lbc in (None, 0, "0"))


def _d1_open_d2_close(bars: list[dict], d_date: str) -> tuple[float | None, float | None]:
    """bars（date 升序）。返 (D+1 open, D+2 close)。D=首板日。

    D 有 bar → D+1=bars[d_idx+1], D+2=bars[d_idx+2]；D 无 bar → D+1=首个 >D 的 bar。
    缺→(None, None)。策略口径标的收益用（≠ Phase 0 隔夜只取 D+1 open）。
    """
    if not bars:
        return (None, None)
    d_idx = None
    for i, b in enumerate(bars):
        if b.get("date") == d_date:
            d_idx = i
            break
    d1_idx = (d_idx + 1) if d_idx is not None else None
    if d1_idx is None:
        for i, b in enumerate(bars):
            if (b.get("date") or "") > d_date:
                d1_idx = i
                break
    if d1_idx is None or d1_idx >= len(bars):
        return (None, None)
    d1_open = _to_float(bars[d1_idx].get("open"))
    d2_close = _to_float(bars[d1_idx + 1].get("close")) if d1_idx + 1 < len(bars) else None
    return (d1_open, d2_close)


def _turn_for_date(bars: list[dict], d_date: str) -> float | None:
    """D 日换手率（baostock turn，%）。D 无 bar→None。"""
    for b in bars:
        if b.get("date") == d_date:
            return _to_float(b.get("turn"))
    return None


def _sector_zt_count_from_pool(pool: list[dict], hybk) -> int:
    """同板块涨停数（pool 含首板+连板；grill-decisions.md "涨停"=all 涨停）。

    hybk 空→0（无法判定板块，视为孤板）。
    """
    if not hybk:
        return 0
    return sum(1 for it in pool if (it.get("hybk") or "") == hybk)


def _normalize_fb(item: dict, pool: list[dict], bars: list[dict], d_date: str,
                  concept_tags: list[str] | None = None) -> dict:
    """normalize 首板 raw pool item → 剔除所需 dict。

    纯函数（bars/pool/concept_tags 已取好传入）。concept_tags 默认空（live 简化：
    暂不 fetch 题材，孤板=sector<2；纯 exclude_layer3 仍支持 concept_tags 参数）。
    """
    return {
        "code": str(item.get("c", "") or "").strip(),
        "name": item.get("n", ""),
        "break_times": _to_float(item.get("zbc")),
        "seal_amount": _to_float(item.get("fund")),
        "float_cap": _to_float(item.get("ltsz")),
        "turnover_pct": _turn_for_date(bars, d_date),
        "sector_zt_count": _sector_zt_count_from_pool(pool, item.get("hybk")),
        "concept_tags": concept_tags or [],
        "hybk": item.get("hybk") or None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# live 主流程（em_zt_topic_pool 历史取数 + baostock kline + matrix 输出）
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_bars_with_turn(code: str, start: str, end: str, bs) -> list[dict]:
    """baostock qfq 日K（date/open/close/turn），比 Phase 0 多 keep turn（层2 换手用）。"""
    from tools.first_board_premium_baseline import _bs_code
    bsc = _bs_code(code)
    if not bsc:
        return []
    fields = "date,open,high,low,close,volume,amount,turn,pctChg,isST"
    try:
        rs = bs.query_history_k_data_plus(bsc, fields, start_date=start, end_date=end, adjustflag="2")
    except Exception:
        return []
    if rs.error_code != "0":
        return []
    bars: list[dict] = []
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            bars.append({"date": d[0], "open": _to_float(d[1]), "close": _to_float(d[4]), "turn": _to_float(d[7])})
        except (ValueError, IndexError):
            continue
    return bars


def _trading_dates_from_baostock(days_back: int, end_date: str) -> list[str]:
    """baostock query_trade_dates → 交易日列表（is_trading=1，升序，≤ end_date）。

    替换 gene_scores.db eastmoney_live（仅 ~26 日限量源）；baostock 给全 A 股交易日历。
    """
    from datetime import datetime, timedelta
    import baostock as bs
    start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days_back)).strftime("%Y-%m-%d")
    dates: list[str] = []
    try:
        lg = bs.login()
        if getattr(lg, "error_code", "0") == "0":
            rs = bs.query_trade_dates(start_date=start, end_date=end_date)
            while rs.error_code == "0" and rs.next():
                d = rs.get_row_data()  # [date, is_trading]
                if len(d) >= 2 and d[1] == "1":
                    dates.append(d[0])
        try:
            bs.logout()
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        print(f"[B1] baostock query_trade_dates 失败: {e}")
    return sorted(dates)


def run_layer_lift(days_back: int = 120, fetch_miss: bool = True) -> dict:
    """B1 live 主入口：逐层 day-paired lift + 四态 → matrix。

    复用 tools.first_board_premium_baseline 数据路径（交易日列表 + baostock 缓存 + 补取）。
    输出 .scratch/s077-layer-lift/matrix.json。题材简化（concept_tags=[]，孤板=sector<2）。
    """
    import json
    from datetime import datetime, timedelta
    from pathlib import Path
    from tools.first_board_premium_baseline import _load_kline_cache, _em_date
    import astock

    out_dir = Path(__file__).resolve().parents[2] / ".scratch" / "s077-layer-lift"
    out_dir.mkdir(parents=True, exist_ok=True)

    cache = _load_kline_cache()
    if not cache:
        print("[B1] 无 kline 缓存，中止")
        return {"error": "no cache"}
    max_cache_date = "0"
    for bars in cache.values():
        if bars:
            last = bars[-1].get("date", "")
            if last > max_cache_date:
                max_cache_date = last
    # baostock 交易日历（替换 gene_scores.db eastmoney_live ~26 日限量源）
    all_dates = _trading_dates_from_baostock(days_back, max_cache_date)
    if not all_dates:
        print("[B1] baostock 交易日历空，中止")
        return {"error": "no dates"}
    # D 需留 D+2 trading 在缓存内；周末/节假日致 D+2 跨日历 ≥3 天，留 7 天 robust margin
    max_d = (datetime.strptime(max_cache_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    cutoff = (datetime.strptime(max_cache_date, "%Y-%m-%d") - timedelta(days=days_back)).strftime("%Y-%m-%d")
    dates = [d for d in all_dates if d < max_d and d >= cutoff]
    if not dates:
        print(f"[B1] 无满足条件交易日（max_cache={max_cache_date}）")
        return {"error": "no valid dates"}
    print(f"[B1] 交易日 {len(dates)}（{dates[0]}~{dates[-1]}），cache max={max_cache_date}")

    # 逐层 by_day 收益（layer0=raw 全首板，layer1/2/3=剔除存活）
    by_day: dict[str, dict[str, list[float]]] = {"layer0": {}, "layer1": {}, "layer2": {}, "layer3": {}}
    n_first_boards = 0

    for di, d_date in enumerate(dates):
        d_compact = _em_date(d_date)
        try:
            pool = astock.em_zt_topic_pool("getTopicZTPool", d_compact, "fbt:asc") or []
        except Exception as e:  # noqa: BLE001
            print(f"[B1] D={d_date} 涨停池取数失败: {e}")
            continue
        if not pool:
            continue
        fb_items = [it for it in pool
                    if _is_first_board(it) and len(str(it.get("c", "") or "").strip()) == 6]
        if not fb_items:
            continue

        # normalize（cache bars 优先；miss 标记后补）
        normalized: list[dict] = []
        bars_by_code: dict[str, list[dict]] = {}
        miss_codes: list[str] = []
        for it in fb_items:
            code = str(it.get("c", "") or "").strip()
            bars = cache.get(code) or []
            if not bars:
                miss_codes.append(code)
            normalized.append(_normalize_fb(it, pool, bars, d_date))
            bars_by_code[code] = bars
        n_first_boards += len(normalized)

        # baostock 补 cache_miss（fetch_miss=False 跳过→cache-hit only，快；每 50 re-login）
        if fetch_miss and miss_codes:
            try:
                import baostock as bs
                if getattr(bs.login(), "error_code", "0") == "0":
                    for i, code in enumerate(sorted(set(miss_codes))):
                        if i and i % 50 == 0:
                            try:
                                bs.logout()
                            except Exception:
                                pass
                            bs.login()
                        start = (datetime.strptime(d_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
                        end = (datetime.strptime(d_date, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
                        bars = _fetch_bars_with_turn(code, start, end, bs)
                        if bars:
                            bars_by_code[code] = bars
                            for fb in normalized:  # 重算该 code 的 turnover（原 bars 空）
                                if fb["code"] == code:
                                    fb["turnover_pct"] = _turn_for_date(bars, d_date)
                    try:
                        bs.logout()
                    except Exception:
                        pass
            except ImportError:
                print("[B1] baostock 未装，cache_miss 股跳过 turn/D+2")

        # 逐层剔除
        layers = apply_layers(normalized)

        # 各层 + raw(layer0) 的策略口径 target_return by_day
        for layer_name, codes in layers.items():
            if layer_name == "excluded":
                continue
            for code in codes:
                bars = bars_by_code.get(code) or []
                d1o, d2c = _d1_open_d2_close(bars, d_date)
                tr = target_return(d1o, d2c)
                if tr is None:
                    continue
                by_day[layer_name].setdefault(d_date, []).append(tr)

        if (di + 1) % 5 == 0 or di + 1 == len(dates):
            print(f"[B1] 进度 {di + 1}/{len(dates)} D={d_date} 累计首板={n_first_boards}", flush=True)

    # raw 基线（layer0）pooled stats
    raw_returns = [r for rs in by_day["layer0"].values() for r in rs]
    raw_stats = {
        "n": len(raw_returns),
        "winrate": round(_winrate(raw_returns), 4),
        "mean_pct": round(statistics.mean(raw_returns), 4) if raw_returns else None,
        "note": "raw 首板基线（无剔除，策略口径 D+2close vs D+1open）",
    }

    # 逐层 day-paired lift + 四态（vs layer0=raw）
    per_layer: dict = {"layer0_raw": raw_stats}
    for layer_name in ("layer1", "layer2", "layer3"):
        surv_by_day = by_day[layer_name]
        lift_res = day_paired_lift(surv_by_day, by_day["layer0"])
        lift = lift_res["winrate_lift_avg"]
        n = lift_res["surv_n_pooled"]
        per_layer[layer_name] = {
            **lift_res, "lift": lift, "n": n,
            "validation_status": four_state(lift, n),
        }

    matrix = {
        "generated_at": datetime.now().isoformat(),
        "params": {"days_back": days_back, "cost_pct": COST_PCT,
                   "date_range": [dates[0], dates[-1]], "n_dates": len(dates)},
        "n_first_boards_total": n_first_boards,
        "thresholds": LAYER_THRESHOLDS,
        "per_layer": per_layer,
        "note": ("策略口径 (D+2close-D+1open)/D+1open；day-paired lift 非池化（§44 防假象）；"
                 "四态 §44；题材简化（concept_tags=[]，孤板=sector<2，后续可接 ths_limit_up_pool）"),
    }
    out_path = out_dir / "matrix.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[B1] 矩阵已存：{out_path}")
    for ln in ("layer0_raw", "layer1", "layer2", "layer3"):
        s = per_layer.get(ln, {})
        print(f"  {ln}: n={s.get('n')} lift={s.get('winrate_lift_avg')} "
              f"status={s.get('validation_status', '-')}")
    return matrix


# ─────────────────────────────────────────────────────────────────────────────
# baostock 算涨停历史（替代 em_zt_topic_pool ~3 周限制；8 月 cache 窗口）
# ─────────────────────────────────────────────────────────────────────────────

def _compute_zt_history(cache: dict[str, list[dict]], pct_threshold: float = 9.9) -> list[dict]:
    """从 baostock kline cache 算涨停历史：每 (code, D) 涨停事件。

    涨停 = ``pctChg >= pct_threshold``（代理：主板 +10% / 创业科创 +20% 抓，ST +5% 漏——首板流本剔 ST）。
    lbc = 连续涨停天数（ending at D）；首板 is_first_board = lbc==1（D-1 非涨停）。
    target_return = (D+1 open → D+2 close) 同 bars（策略口径）。
    turnover_pct = D 日 turn。

    纯函数（cache 入参），可离线测。仅 cache 命中 codes（baostock 补路径不 keep pctChg）。
    """
    events: list[dict] = []
    for code, bars in cache.items():
        if not bars:
            continue
        # 涨停 mask
        is_zt: list[bool] = []
        for b in bars:
            pct = _to_float(b.get("pctChg"))
            is_zt.append(pct is not None and pct >= pct_threshold)
        for i, b in enumerate(bars):
            if not is_zt[i]:
                continue
            # lbc = 连续涨停 ending at i（往前数）
            lbc = 1
            j = i - 1
            while j >= 0 and is_zt[j]:
                lbc += 1
                j -= 1
            d1_open = _to_float(bars[i + 1].get("open")) if i + 1 < len(bars) else None
            d2_close = _to_float(bars[i + 2].get("close")) if i + 2 < len(bars) else None
            events.append({
                "date": b.get("date"), "code": code, "lbc": lbc,
                "is_first_board": lbc == 1,
                "d1_open": d1_open, "d2_close": d2_close,
                "target_return": target_return(d1_open, d2_close),
                "turnover_pct": _to_float(b.get("turn")),
            })
    return events


def _compute_movers(cache: dict[str, list[dict]], pct_lo: float, pct_hi: float,
                     turn_min: float | None = None) -> tuple[dict, dict]:
    """扫 cache：movers = D pctChg in [lo, hi) 的 target_return by day；
    non_movers = 其余（pctChg 不在该档但有 D+1/D+2）by day。disjoint，within-subset baseline。
    """
    movers: dict[str, list[float]] = {}
    non_movers: dict[str, list[float]] = {}
    for code, bars in cache.items():
        if not bars:
            continue
        for i, b in enumerate(bars):
            d1_open = _to_float(bars[i + 1].get("open")) if i + 1 < len(bars) else None
            d2_close = _to_float(bars[i + 2].get("close")) if i + 2 < len(bars) else None
            tr = target_return(d1_open, d2_close)
            if tr is None:
                continue
            d = b.get("date")
            pct = _to_float(b.get("pctChg"))
            turn = _to_float(b.get("turn"))
            is_mover = pct is not None and pct_lo <= pct < pct_hi
            if turn_min is not None:
                is_mover = is_mover and (turn is not None and turn >= turn_min)
            if is_mover:
                movers.setdefault(d, []).append(tr)
            else:
                non_movers.setdefault(d, []).append(tr)
    return movers, non_movers


def run_momentum_broaden(pct_lo: float = 5.0, pct_hi: float = 9.9) -> dict:
    """动量放宽 §44 first signal：pctChg [lo, hi) 强势股（非涨停）D+1→D+2 收益 vs non_movers。

    within-subset day-paired lift（1121 cache codes proxy baseline，非 §44 真 day-cluster-random；
    涨停-prone 选择偏，lift 内抵消）。baostock cache 8 月窗口，秒级。输出 matrix_momentum.json。
    """
    import json
    from pathlib import Path
    from tools.first_board_premium_baseline import _load_kline_cache

    cache = _load_kline_cache()
    if not cache:
        print("[momentum] 无 kline cache，中止")
        return {"error": "no cache"}
    movers, non_movers = _compute_movers(cache, pct_lo, pct_hi)
    movers_returns = [r for rs in movers.values() for r in rs]
    nm_returns = [r for rs in non_movers.values() for r in rs]
    lift_res = day_paired_lift(movers, non_movers)
    lift = lift_res["winrate_lift_avg"]
    n = lift_res["surv_n_pooled"]
    matrix = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "mode": f"momentum-broaden (pctChg {pct_lo}-{pct_hi}%, non-涨停 strong)",
        "movers": {"n": len(movers_returns), "winrate": round(_winrate(movers_returns), 4),
                   "mean_pct": round(statistics.mean(movers_returns), 4) if movers_returns else None,
                   "n_dates": len(movers)},
        "non_movers_baseline": {"n": len(nm_returns), "winrate": round(_winrate(nm_returns), 4),
                                 "mean_pct": round(statistics.mean(nm_returns), 4) if nm_returns else None},
        "lift": lift, "n": n, "validation_status": four_state(lift, n),
        "note": "within-subset day-paired（1121 cache proxy baseline，非 §44 真 day-cluster-random；lift 内抵消）",
    }
    out_dir = Path(__file__).resolve().parents[2] / ".scratch" / "s077-layer-lift"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "matrix_momentum.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[momentum] 矩阵已存：{out_path}")
    print(f"  movers: n={len(movers_returns)} winrate={matrix['movers']['winrate']} "
          f"mean={matrix['movers']['mean_pct']} dates={matrix['movers']['n_dates']}")
    print(f"  non_movers: n={len(nm_returns)} winrate={matrix['non_movers_baseline']['winrate']}")
    print(f"  lift={lift} n={n} status={matrix['validation_status']}")
    return matrix


def run_layer_lift_baostock() -> dict:
    """B1 over baostock-computed 涨停历史（8 月 cache 窗口，秒级）。

    不调 em_zt_topic_pool（绕开 ~3 周限制）；层1/3 跳过（baostock 无 zbc/fund/hybk），
    只验 raw 首板 + 层2（换手>30%）剔除。涨停代理 pctChg>=9.9；1121 cache codes 选择偏（lift 内抵消）。
    输出 .scratch/s077-layer-lift/matrix_baostock.json。
    """
    import json
    from pathlib import Path
    from tools.first_board_premium_baseline import _load_kline_cache

    cache = _load_kline_cache()
    if not cache:
        print("[B1-baostock] 无 kline cache，中止")
        return {"error": "no cache"}
    events = _compute_zt_history(cache)
    n_zt = len(events)
    n_fb = sum(1 for e in events if e["is_first_board"])
    print(f"[B1-baostock] cache {len(cache)} codes, 涨停事件 {n_zt}, 首板 {n_fb}")

    raw_by_day: dict[str, list[float]] = {}
    l2_by_day: dict[str, list[float]] = {}
    for e in events:
        if not e["is_first_board"]:
            continue
        tr = e["target_return"]
        if tr is None:
            continue
        raw_by_day.setdefault(e["date"], []).append(tr)
        # 层2：换手>30% 剔除
        tp = e["turnover_pct"]
        if tp is not None and tp > LAYER_THRESHOLDS["max_turnover"]:
            continue
        l2_by_day.setdefault(e["date"], []).append(tr)

    raw_returns = [r for rs in raw_by_day.values() for r in rs]
    raw_stats = {
        "n": len(raw_returns), "winrate": round(_winrate(raw_returns), 4),
        "mean_pct": round(statistics.mean(raw_returns), 4) if raw_returns else None,
        "n_dates": len(raw_by_day),
        "note": "raw 首板基线（baostock 算，pctChg>=9.9 代理，8 月 cache 窗口）",
    }
    l2_lift = day_paired_lift(l2_by_day, raw_by_day)
    lift = l2_lift["winrate_lift_avg"]
    n = l2_lift["surv_n_pooled"]
    l2_stats = {**l2_lift, "lift": lift, "n": n, "validation_status": four_state(lift, n)}

    matrix = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "mode": "baostock-computed (pctChg>=9.9 代理)",
        "n_codes": len(cache), "n_zt_events": n_zt, "n_first_boards": n_fb,
        "raw_first_board": raw_stats,
        "layer2_turnover": l2_stats,
        "note": ("涨停代理 pctChg>=9.9（主板+10%/创业+20%抓，ST漏）；层1/3 跳过"
                 "（baostock 无 zbc/fund/hybk）；1121 cache codes 选择偏（lift 内抵消）"),
    }
    out_dir = Path(__file__).resolve().parents[2] / ".scratch" / "s077-layer-lift"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "matrix_baostock.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[B1-baostock] 矩阵已存：{out_path}")
    print(f"  raw_first_board: n={raw_stats['n']} winrate={raw_stats['winrate']} "
          f"mean={raw_stats['mean_pct']} dates={raw_stats['n_dates']}")
    print(f"  layer2_turnover: n={n} lift={lift} status={l2_stats['validation_status']}")
    return matrix


def run_momentum_scan() -> dict:
    """pctChg 区间 × {无放量, 放量(turn>=5)} 扫描 lift，找最优组合。baostock cache 8 月，秒级。"""
    import json
    from datetime import datetime
    from pathlib import Path
    from tools.first_board_premium_baseline import _load_kline_cache

    cache = _load_kline_cache()
    if not cache:
        print("[momentum-scan] 无 kline cache，中止")
        return {"error": "no cache"}
    ranges = [(0.0, 3.0, "跌平0-3"), (3.0, 5.0, "温和3-5"), (5.0, 7.0, "强势5-7"),
              (7.0, 9.9, "近涨停7-9.9"), (9.9, 11.0, "涨停9.9+"), (5.0, 9.9, "动量放宽5-9.9")]
    vols = [(None, "无放量"), (5.0, "放量turn>=5")]
    results = []
    for lo, hi, label in ranges:
        for turn_min, vol_label in vols:
            movers, non_movers = _compute_movers(cache, lo, hi, turn_min=turn_min)
            mr = [r for rs in movers.values() for r in rs]
            if not mr:
                results.append({"range": label, "vol": vol_label, "n": 0, "lift": None, "status": "-"})
                continue
            lift_res = day_paired_lift(movers, non_movers)
            lift = lift_res["winrate_lift_avg"]
            n = lift_res["surv_n_pooled"]
            results.append({
                "range": label, "vol": vol_label, "n": n,
                "movers_winrate": round(_winrate(mr), 4),
                "movers_mean": round(statistics.mean(mr), 4),
                "lift": lift, "status": four_state(lift, n),
            })
    out_dir = Path(__file__).resolve().parents[2] / ".scratch" / "s077-layer-lift"
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = {"generated_at": datetime.now().isoformat(), "mode": "momentum-scan", "results": results}
    out_path = out_dir / "matrix_momentum_scan.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[momentum-scan] 表已存：{out_path}")
    print(f"  {'range':<16} {'vol':<12} {'n':<7} {'winrate':<8} {'lift':<8} status")
    for r in results:
        print(f"  {r['range']:<16} {r['vol']:<12} {r['n']:<7} "
              f"{str(r.get('movers_winrate', '-')):<8} {str(r['lift']):<8} {r['status']}")
    return matrix


def main(argv: list[str] | None = None) -> int:
    import sys
    argv = list(argv) if argv is not None else list(sys.argv[1:])
    if "--momentum-scan" in argv:
        run_momentum_scan()
        return 0
    if "--momentum-broaden" in argv:
        run_momentum_broaden()
        return 0
    if "--baostock-history" in argv:
        run_layer_lift_baostock()
        return 0
    days = 120
    fetch_miss = True
    for i, a in enumerate(argv):
        if a == "--days" and i + 1 < len(argv):
            days = int(argv[i + 1])
        elif a == "--no-fetch":
            fetch_miss = False
    run_layer_lift(days, fetch_miss=fetch_miss)
    return 0


if __name__ == "__main__":
    main()
