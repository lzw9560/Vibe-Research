# -*- coding: utf-8 -*-
"""S075 Phase 2 候选确认（tasks.md 027-033）——T 日盘前对候选池逐只做实时确认。

输入：candidates（来自 first_board_filter 的 scored_candidates，T-1 盘后产出）
输出：竞价过滤 + 开盘确认结果，落盘 5 维度值供回测。

**数据源约束（必须遵守）**：
1. 5 分钟 K 线不可用（mootdx/astock.kline 只到 60 分钟线，tickflow 只到日 K）。
   → 降级方案：用 tencent_quote 实时价轮询替代（9:30-9:35 每分钟取 price），
     判定"5 分钟不破开盘价"。
2. market._emotion() 在 9:25 返回 T-1 数据——max_boards 用 T-1 粗筛，
   9:30 后复调用更新（本任务不实现更新，只标注）。
3. tencent_quote 签名：tencent_quote(codes: list[str]) -> dict[str, dict]，
   字段：name/price(最新价)/last_close(昨收)/open(开盘价)/vol_ratio(量比)/
   amount_wan(成交额万)/turnover_pct(换手率)/change_pct(涨跌幅)。
   ⚠️ 无 `last` 字段——spec 描述的 `last` 实际是 `price`（最新价/现价）。

**5 维度强势确认（spec 2.3）**：
① 竞价高开 1-3% → auction_open_pct（必要，tencent_quote 算）
② 量比 >1.5 → vol_ratio（必要，tencent_quote 取）
③ 开盘价支撑 5 分钟不破 → open_held（必要，降级用轮询采样）
④ 竞价量 >= 昨日 5% 成交量 → auction_vol_ratio（参考，落盘不阻断）
⑤ 盘口买压 买一>卖一 3 倍 → 人工标注（参考，落盘字段预留 manual_bid_ask_ratio）

确认逻辑：①②③ 全满足 → confirmed=True；有 1 项不满足 → dropped。
④⑤ 参考，落盘但不阻断（标注"30 天后回测是否有效"）。

**同步骨架**：本模块不做轮询，接收已采集数据；轮询逻辑由调度层驱动。
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from astock import tencent_quote  # noqa: E402

_logger = logging.getLogger(__name__)

# ===========================================================================
# 阈值配置（待回测校准，30 天后用实际数据调）
# ===========================================================================
# 所有阈值集中在此常量，顶部统一管理。当前值为骨架占位，非回测校准值。
# 标注"待回测校准"：实际阈值需用 30 天首板候选确认数据回测后调整。
CONFIRM_THRESHOLDS: dict = {
    # ── 竞价过滤（027-028）─────────────────────────────────────────────
    "auction_high_max": 5.0,        # 高开 >5% 剔除（追高风险）
    "auction_high_min": 1.0,        # 高开 1-3% 健康区间
    "auction_high_good_max": 3.0,   # 高开 1-3% 健康区间上限
    "auction_high_observe_max": 5.0, # 高开 3-5% 保留但标"偏大观察"
    "auction_low_max": 0.0,         # 低开 ≤0% 剔除（核按钮风险）
    # ── 开盘确认（030-033）─────────────────────────────────────────────
    "open_vol_ratio_min": 1.5,      # 量比 >1.5（必要条件②）
    "open_sample_count": 5,         # 9:31-9:35 共 5 个采样点
}


# ===========================================================================
# 027-028 竞价确认（T 日 9:25）
# ===========================================================================

def fetch_auction_data(candidate_codes: list[str]) -> dict[str, dict]:
    """T 日 9:25 调 tencent_quote 取候选每只竞价数据。

    Args:
        candidate_codes: 候选股代码 list[str]。

    Returns:
        dict[str, dict]：{code: {auction_open, last_close, auction_open_pct,
        auction_amount_wan}}。
        - auction_open: 开盘价（tencent_quote 的 open 字段）
        - last_close: 昨收价
        - auction_open_pct: 高开幅度（auction_open - last_close）/last_close*100
        - auction_amount_wan: 竞价成交额（万元，tencent_quote 的 amount_wan）
        数据缺失/请求失败 → 空 dict {}（不崩，调用方跳过该股）。
    """
    if not candidate_codes:
        return {}
    try:
        quotes = tencent_quote(candidate_codes)
    except Exception as e:
        _logger.warning("fetch_auction_data tencent_quote 失败 err=%s", e)
        return {}
    if not quotes:
        return {}

    out: dict[str, dict] = {}
    for code, q in quotes.items():
        if not q or not isinstance(q, dict):
            continue
        open_price = _to_float(q.get("open"))
        last_close = _to_float(q.get("last_close"))
        amount_wan = _to_float(q.get("amount_wan"))
        if open_price is None or last_close is None or last_close <= 0:
            continue
        pct = (open_price - last_close) / last_close * 100
        out[code] = {
            "auction_open": open_price,
            "last_close": last_close,
            "auction_open_pct": round(pct, 2),
            "auction_amount_wan": amount_wan,
        }
    return out


def filter_by_auction(
    candidates: list[dict], auction_data: dict,
) -> tuple[list[dict], list[dict]]:
    """竞价过滤。

    Args:
        candidates: scored_candidates list[dict]（含 code）。
        auction_data: fetch_auction_data 返回的 {code: {...}}。

    Returns:
        (confirmed, dropped)：
        - confirmed: 保留候选 list[dict]（附 auction 字段）
        - dropped: 剔除记录 list[dict]，每项 {code, reason}

    规则（标注"待回测校准"）：
    - 高开 >5% → drop "高开>5%追高风险"
    - 低开（≤0）→ drop "低开核按钮风险"
    - 高开 1-3% → 保留（健康区间）
    - 高开 3-5% → 保留但标"高开偏大观察"（不剔除，落盘标注）
    - 数据缺失 → 不剔除（不因数据缺失误剔除，标"竞价数据缺失"降级保留）

    ⚠️ auction_data 缺失的候选 → 降级保留（不剔除），标注"竞价数据缺失"。
    """
    confirmed: list[dict] = []
    dropped: list[dict] = []

    high_max = CONFIRM_THRESHOLDS["auction_high_max"]
    high_min = CONFIRM_THRESHOLDS["auction_high_min"]
    good_max = CONFIRM_THRESHOLDS["auction_high_good_max"]
    observe_max = CONFIRM_THRESHOLDS["auction_high_observe_max"]
    low_max = CONFIRM_THRESHOLDS["auction_low_max"]

    for cand in candidates:
        code = cand.get("code", "")
        ad = auction_data.get(code)

        # 数据缺失 → 降级保留（不因数据缺失误剔除）
        if not ad:
            new_cand = {**cand, "auction": {"note": "竞价数据缺失"}}
            confirmed.append(new_cand)
            continue

        pct = ad.get("auction_open_pct", 0.0)
        new_cand = {**cand, "auction": ad}

        # 规则1：高开 >5% → 剔除（追高风险）
        if pct > high_max:
            dropped.append({
                "code": code,
                "reason": f"高开{pct:.1f}%>5%追高风险",
            })
            continue

        # 规则2：低开 ≤0% → 剔除（核按钮风险）
        if pct <= low_max:
            dropped.append({
                "code": code,
                "reason": f"低开{pct:.1f}%核按钮风险",
            })
            continue

        # 规则3：高开 3-5% → 保留但标"偏大观察"
        if good_max < pct <= observe_max:
            new_cand["auction"]["note"] = f"高开{pct:.1f}%偏大观察"
        # 规则4：高开 1-3% → 健康区间（默认保留）

        confirmed.append(new_cand)

    return confirmed, dropped


# ===========================================================================
# 030-033 开盘 10 分钟确认（T 日 9:30-9:35）
# ===========================================================================

def fetch_open_price(code: str) -> float | None:
    """T 日 9:30 调 tencent_quote 取开盘价。

    Args:
        code: 6 位股票代码。

    Returns:
        开盘价（tencent_quote 的 open 字段）或 None（数据缺失）。
    """
    try:
        quotes = tencent_quote([code])
    except Exception as e:
        _logger.warning("fetch_open_price tencent_quote 失败 code=%s err=%s", code, e)
        return None
    q = quotes.get(code) if quotes else None
    if not q or not isinstance(q, dict):
        return None
    return _to_float(q.get("open"))


def check_open_support(code: str, open_price: float, samples: list[float]) -> dict:
    """开盘确认判定（降级版，无 5 分钟 K 线）。

    ⚠️ 降级方案：无 5 分钟 K 线，用 tencent_quote 实时价轮询采样替代。
    samples = 9:31-9:35 每分钟取的 price（5 个采样点）。
    open_held = all(s >= open_price for s in samples)（5 分钟不破开盘价）。

    Args:
        code: 6 位股票代码。
        open_price: 开盘价（fetch_open_price 取）。
        samples: 9:31-9:35 每分钟 current price 采样 list[float]。

    Returns:
        dict 含：
        - code: str
        - open_price: float
        - min_low: float | None（samples 最低价）
        - open_held: bool（5 分钟不破开盘价，samples 空 → False）
        - vol_ratio: float | None（从 tencent_quote 取）
        - confirmed: bool（open_held and vol_ratio > 1.5）
        - samples: list[float]（落盘供回测）
    """
    # 取实时量比（tencent_quote 60s 缓存，重复调用不重复请求）
    vol_ratio: float | None = None
    try:
        quotes = tencent_quote([code])
        q = quotes.get(code) if quotes else None
        if q and isinstance(q, dict):
            vol_ratio = _to_float(q.get("vol_ratio"))
    except Exception as e:
        _logger.debug("check_open_support vol_ratio 取数失败 code=%s err=%s", code, e)

    # 开盘价支撑判定（降级：用 samples 轮询替代 5 分钟 K 线）
    min_low = min(samples) if samples else None
    # open_held = 所有采样点都 >= open_price（5 分钟不破）
    open_held = bool(samples) and all(s >= open_price for s in samples)

    # confirmed = ①②③ 全满足（①在竞价层已过滤，②③在此判定）
    vol_ratio_threshold = CONFIRM_THRESHOLDS["open_vol_ratio_min"]
    vol_ok = (vol_ratio is not None and vol_ratio > vol_ratio_threshold)
    confirmed = open_held and vol_ok

    return {
        "code": code,
        "open_price": open_price,
        "min_low": min_low,
        "open_held": open_held,
        "vol_ratio": vol_ratio,
        "vol_ratio_ok": vol_ok,
        "confirmed": confirmed,
        "samples": samples,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def confirm_candidates(
    candidates: list[dict], open_samples: dict,
) -> list[dict]:
    """对竞价确认的候选逐只做开盘确认。

    Args:
        candidates: 竞价确认后的候选 list[dict]（含 code + auction 字段）。
        open_samples: T 日 9:31-9:35 轮询采样的 {code: [price1..price5]}。

    Returns:
        list[dict] 含 {code, open_price, min_low, open_held, vol_ratio, confirmed, samples}。

    注：本函数是同步骨架，接收已采集的 samples，不做轮询。
    轮询逻辑由调度层（scheduled_tasks 或前端 polling）驱动。
    samples 缺失的候选 → confirmed=False，标注"采样数据缺失"。
    """
    out: list[dict] = []
    for cand in candidates:
        code = cand.get("code", "")
        samples = open_samples.get(code) or []

        # 取开盘价（优先用竞价数据的 auction_open，降级实时取）
        open_price = None
        auction = cand.get("auction") or {}
        if isinstance(auction, dict):
            open_price = _to_float(auction.get("auction_open"))
        if open_price is None:
            open_price = fetch_open_price(code)

        if open_price is None:
            # 开盘价缺失 → 降级，confirmed=False
            out.append({
                "code": code,
                "open_price": None,
                "min_low": None,
                "open_held": False,
                "vol_ratio": None,
                "vol_ratio_ok": False,
                "confirmed": False,
                "samples": samples,
                "note": "开盘价缺失",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            continue

        result = check_open_support(code, open_price, samples)
        # 合并原候选的 score/auction 字段（落盘供回测）
        result["total"] = cand.get("total")
        result["auction"] = auction
        out.append(result)

    return out


# ===========================================================================
# 主入口
# ===========================================================================

def run_first_board_confirm(
    candidates: list[dict],
    auction_data: dict | None = None,
    open_samples: dict | None = None,
) -> dict:
    """Phase 2 主入口。

    Args:
        candidates: 来自 first_board_filter 的 scored_candidates。
        auction_data: T 日 9:25 竞价数据（fetch_auction_data 产出）。
                      None → 内部调 fetch_auction_data 取（盘前实时）。
        open_samples: T 日 9:31-9:35 轮询采样的 {code: [price1..price5]}。
                      None → 内部不做开盘确认（返空 open_confirmed）。

    Returns:
        dict 含：
        - auction_confirmed: list[dict]（竞价过滤后保留，附 auction 字段）
        - auction_dropped: list[dict]（竞价剔除 [{code, reason}]）
        - open_confirmed: list[dict]（开盘确认，①②③全满足）
        - open_dropped: list[dict]（开盘未确认）
        - confirm_records: list[dict]（全部落盘记录，含 5 维度值）
    """
    codes = [c.get("code", "") for c in candidates if c.get("code")]

    # 027-028 竞价确认
    if auction_data is None:
        auction_data = fetch_auction_data(codes)
    auction_confirmed, auction_dropped = filter_by_auction(candidates, auction_data)

    # 030-033 开盘确认（需 open_samples，否则跳过）
    open_confirmed: list[dict] = []
    open_dropped: list[dict] = []
    if open_samples is not None:
        results = confirm_candidates(auction_confirmed, open_samples)
        for r in results:
            if r.get("confirmed"):
                open_confirmed.append(r)
            else:
                open_dropped.append(r)

    # confirm_records：全部落盘记录（含 5 维度值）
    # ① auction_open_pct ② vol_ratio ③ open_held ④ auction_vol_ratio ⑤ manual_bid_ask_ratio
    confirm_records: list[dict] = []
    # 竞价剔除记录
    for d in auction_dropped:
        confirm_records.append({
            "code": d["code"],
            "stage": "auction",
            "confirmed": False,
            "reason": d["reason"],
            # 5 维度值（竞价剔除的只有 ①）
            "auction_open_pct": _safe_pct(auction_data, d["code"]),
            "vol_ratio": None,
            "open_held": None,
            "auction_vol_ratio": _safe_vol_ratio(auction_data, d["code"]),
            "manual_bid_ask_ratio": None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    # 开盘确认记录（含 open_confirmed + open_dropped）
    for r in (open_confirmed + open_dropped):
        auction = r.get("auction") or {}
        confirm_records.append({
            "code": r.get("code", ""),
            "stage": "open",
            "confirmed": r.get("confirmed", False),
            "open_price": r.get("open_price"),
            "min_low": r.get("min_low"),
            "open_held": r.get("open_held"),
            "vol_ratio": r.get("vol_ratio"),
            "vol_ratio_ok": r.get("vol_ratio_ok"),
            "samples": r.get("samples"),
            # 5 维度值
            "auction_open_pct": auction.get("auction_open_pct") if isinstance(auction, dict) else None,
            "auction_vol_ratio": _calc_auction_vol_ratio(auction),
            "manual_bid_ask_ratio": None,  # ⑤ 人工标注，字段预留
            "total": r.get("total"),
            "note": r.get("note", auction.get("note") if isinstance(auction, dict) else None),
            "timestamp": r.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        })

    return {
        "auction_confirmed": auction_confirmed,
        "auction_dropped": auction_dropped,
        "open_confirmed": open_confirmed,
        "open_dropped": open_dropped,
        "confirm_records": confirm_records,
    }


# ===========================================================================
# 辅助函数
# ===========================================================================

def _to_float(v) -> float | None:
    """raw 字段归一 float 或 None。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_pct(auction_data: dict, code: str) -> float | None:
    """安全取 auction_open_pct。"""
    ad = auction_data.get(code) if auction_data else None
    if not ad or not isinstance(ad, dict):
        return None
    return _to_float(ad.get("auction_open_pct"))


def _safe_vol_ratio(auction_data: dict, code: str) -> float | None:
    """安全取竞价量比（④参考维度，用 auction_amount_wan 近似）。

    spec ④：竞价量 >= 昨日 5% 成交量。tencent_quote 无昨日成交量字段，
    用 auction_amount_wan（竞价成交额万）近似落盘，标注"参考，30天后回测"。
    """
    ad = auction_data.get(code) if auction_data else None
    if not ad or not isinstance(ad, dict):
        return None
    return _to_float(ad.get("auction_amount_wan"))


def _calc_auction_vol_ratio(auction: dict) -> float | None:
    """从 auction dict 取竞价量（④参考维度）。

    auction = {auction_open, last_close, auction_open_pct, auction_amount_wan}
    返 auction_amount_wan（万元），作为竞价量参考值。
    无数据 → None。
    """
    if not auction or not isinstance(auction, dict):
        return None
    return _to_float(auction.get("auction_amount_wan"))


if __name__ == "__main__":
    # 骨架自测：python -m strategies.first_board_confirm
    cands = [
        {"code": "001358", "name": "兴欣新材", "total": 63.4},
        {"code": "600127", "name": "金健米业", "total": 60.0},
    ]
    auction = {
        "001358": {"auction_open": 10.21, "last_close": 10.0,
                   "auction_open_pct": 2.1, "auction_amount_wan": 5000},
        "600127": {"auction_open": 5.30, "last_close": 5.0,
                   "auction_open_pct": 6.0, "auction_amount_wan": 3000},
    }
    samples = {
        "001358": [10.21, 10.25, 10.30, 10.28, 10.35],
        "600127": [5.30, 5.28, 5.20, 5.15, 5.10],
    }
    r = run_first_board_confirm(cands, auction, samples)
    print(f"竞价确认: {len(r['auction_confirmed'])}")
    print(f"竞价剔除: {len(r['auction_dropped'])}")
    print(f"开盘确认: {len(r['open_confirmed'])}")
    print(f"开盘剔除: {len(r['open_dropped'])}")
    for c in r["open_confirmed"]:
        print(f"  OK {c['code']} open_held={c['open_held']} vol_ratio={c.get('vol_ratio')}")
    for c in r["open_dropped"]:
        print(f"  X  {c['code']} open_held={c.get('open_held')} note={c.get('note')}")
