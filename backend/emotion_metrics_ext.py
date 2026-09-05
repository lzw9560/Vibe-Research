"""派生情绪指标 —— 短线复盘真正的命根子。

S149 Phase 2：移植自 vibe-astock@3c3b7c8 emotion_metrics.py 的 6 个公开函数
（money_effect / consec_premium / cycle_position / build_metrics / render_metrics
/ day_summary）+ 分层明细 consec_premium_detail（spec §2 分层要求新增）。
promotion_rates / ladder_gap 参照不移植——market.py::_emotion 已有，§1.4 冻结
本期指标清单为赚钱效应/连板溢价/情绪周期三个。

# derived from vibe-astock@3c3b7c8 (github.com/lzw9560), Apache-2.0, modified
# Original author: Simon Lin (simonlin0423@gmail.com)
"""
from __future__ import annotations

import json
import os
from statistics import mean, median
from typing import Optional

# ── 改写 1-4：指向 Vibe-Research 基建（不裸调 urllib/akshare/requests，走防封）──
# P2-T2a：batch_pct 内联 urllib qt.gtimg.cn → tencent.fetch_raw（提取 change_pct）
from data.sources.tencent import fetch_raw
# P2-T2b/d：fetch_zt_pool / fetch_prev_pool → astock.em_zt_topic_pool（push2ex，em_get 防封）
from astock import em_zt_topic_pool
# trade_calendar 4 函数 + atomic_write_json（P4-T1 已移植到 vibe_astock_util）
from utils.vibe_astock_util import (
    atomic_write_json,
    china_today,
    is_settled,
    live_quotes_are_close_of,
    trade_dates_ending_at,
)
from vr_paths import prev_trading_date, resolve_data_dir

_BATCH = 50  # 腾讯批量行情单批上限（保守值）——fetch_raw 单 URL 全量发，分批隔离单批失败


# ─────────────────────────── P2-T2a：batch_pct ───────────────────────────
def batch_pct(codes: list[str]) -> dict[str, float]:
    """批量取当前涨跌幅 {code: pct}。

    改写自 vibe-astock emotion_metrics.py::batch_pct——原内联 urllib 裸调
    qt.gtimg.cn，现走 data.sources.tencent.fetch_raw（60s TTL 缓存 + 防封底座，
    28 个消费者共用单一事实源），提取 change_pct 字段（num(32)，与原 _F_PCT=32 一致）。

    忠实保留源的分批 + 失败隔离（source:29-51 "单批失败只丢该批不影响其它批"）：
    fetch_raw 单 URL 全量发送（tencent.py:_fetch_gtimg 无自分批），故按 _BATCH=50
    外层分批调 fetch_raw，每批独立 try/except——单批超时/失败只丢该批，其余批次仍返部分数据
    （牛市涨停池 150-200 只时避免单次失败全量返空 → coverage_rate=0 误报不可用）。
    """
    uniq = list(dict.fromkeys(str(c).zfill(6) for c in codes if c))
    if not uniq:
        return {}
    out: dict[str, float] = {}
    for i in range(0, len(uniq), _BATCH):
        chunk = uniq[i : i + _BATCH]
        try:
            raw = fetch_raw(chunk)
        except Exception:  # noqa: BLE001  单批失败不拖累整体
            continue
        for code, q in raw.items():
            pct = q.get("change_pct")
            if pct is not None:
                out[str(code).zfill(6)] = float(pct)
    return out


# ─────────────────────────── _zt_pool（getTopicZTPool）───────────────────
_POOL_CACHE: dict[str, dict] = {}
_POOL_CACHE_MAX = 240  # 约一年交易日；上界防常驻进程无限增长


def _zt_pool(date: str) -> Optional[dict]:
    """取某日涨停池；失败/空返回 None（不把失败伪装成 0 家）。

    改写自源 _zt_pool——原 dr.fetch_zt_pool(date) 返 {zt:DataFrame, ladder, zb_count,
    highest_consec, error_zt}；现 em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")
    返 list[dict]（push2ex 原始行），本函数将其归一为同构 dict：
      zt: list[dict]（原始池行）/ ladder: [{code,name,boards}] / zb_count / highest_consec / error_zt
    zb_count 取 getTopicZBPool（炸板池）行数——源结构含 zb_count，此处等价补齐。
    """
    settled = is_settled(date)
    if settled and date in _POOL_CACHE:
        return _POOL_CACHE[date]
    compact = date.replace("-", "")
    try:
        rows = em_zt_topic_pool("getTopicZTPool", compact, "fbt:asc")
        zb_rows = em_zt_topic_pool("getTopicZBPool", compact, "fbt:asc")
    except Exception:  # noqa: BLE001  源断返 None，不伪装
        return None
    if not rows:
        # 空池（非交易日 / 无涨停）：与源 zt.get("zt") is None 同义
        return None
    out = {
        "zt": rows,
        "ladder": _ladder_by_boards_raw(rows),
        "zb_count": len(zb_rows or []),
        "highest_consec": max(
            (int(r.get("lbc") or 1) for r in rows), default=0
        ),
        "error_zt": None,
    }
    if settled:
        if len(_POOL_CACHE) >= _POOL_CACHE_MAX:
            _POOL_CACHE.pop(next(iter(_POOL_CACHE)), None)  # 简单 FIFO
        _POOL_CACHE[date] = out
    return out


def _ladder_by_boards_raw(rows: list[dict]) -> list[dict]:
    """涨停池行的连板梯队，每项 {code, name, boards}。字段映射：c→code, n→name, lbc→boards。"""
    return [
        {"code": str(r.get("c", "")).zfill(6),
         "name": r.get("n", ""),
         "boards": int(r.get("lbc") or 1)}
        for r in (rows or [])
        if r.get("c")
    ]


def _ladder_by_boards(zt: dict) -> list[dict]:
    """涨停池的连板梯队（从归一 dict 取）。"""
    return _ladder_by_boards_raw(zt.get("zt") or [])


def _pool_codes(zt: dict) -> set[str]:
    """涨停池全部代码集合（用于判断"今日是否仍涨停"）。

    改写自源 _pool_codes——原读 DataFrame 列（代码/code/股票代码）；现 push2ex
    list[dict] 直接取每行 c 字段。
    """
    return {str(r.get("c", "")).zfill(6) for r in (zt.get("zt") or []) if r.get("c")}


# ─────────────────────── 覆盖率闸门（保留源逻辑）───────────────────────
_COVERAGE_MIN = 0.5
_COVERAGE_PARTIAL = 0.9


def _coverage(vals: list[float], expected: int) -> dict:
    """样本覆盖情况。expected = 本该拿到的只数。"""
    rate = round(len(vals) / expected, 3) if expected else None
    return {
        "sample": len(vals),
        "expected_sample": expected,
        "coverage_rate": rate,
        "partial": bool(rate is not None and rate < _COVERAGE_PARTIAL),
    }


# ─────────────────────── P2-T2b：_settled_pool（getYesterdayZTPool）───────────────────────
def _settled_pool(date: str) -> Optional[list[dict]]:
    """date 那一场的**定稿记录**：昨日涨停股在 date 当天的表现。

    每行自带 ret（该股在 date 的涨跌幅）/ prev_boards / close / limit_price
    ——"昨天进去的人赚不赚钱"这一整段不需要实时行情也算得出。

    改写自源 _settled_pool→fetch_prev_pool——原走 akshare stock_zt_pool_previous_em
    （datacenter，裸调无防封）；现走 astock.em_zt_topic_pool("getYesterdayZTPool",
    date, "zs:desc")（push2ex，em_get 防封）。

    ⚠️ sort 必须用 zs:desc（akshare 源码同款）——fbt:asc 实测返空池（P2 探测确认）。

    字段映射表（push2ex → fetch_prev_pool 目标形状）：
      c→code / n→name / zdp→ret / ylbc→prev_boards / yfbt→seal_time /
      hybk→sector / p(厘)→close(元,÷1000) / ztp(厘)→limit_price(元,÷1000)
    单位 ÷1000 对齐 market.py:370 约定（push2ex p 为厘，tencent price 为元）。
    is_limit_up 的 abs(close-limit)<0.011 在元单位下鲁棒：涨停精确 close==limit_price
    →diff=0；近涨停 diff≥0.5（一档=0.01元=10厘）。
    """
    compact = date.replace("-", "")
    try:
        rows = em_zt_topic_pool("getYesterdayZTPool", compact, "zs:desc")
    except Exception:  # noqa: BLE001  取不到退回实时那条路
        return None
    if not rows:
        return None
    out: list[dict] = []
    for r in rows:
        try:
            close = _safe_price(r.get("p"))
            limit_price = _safe_price(r.get("ztp"))
            out.append({
                "code": str(r.get("c", "")).zfill(6),
                "name": str(r.get("n", "")),
                "ret": float(r["zdp"]) if r.get("zdp") is not None else None,
                "prev_boards": int(r.get("ylbc") or 0),
                "seal_time": str(r.get("yfbt") or ""),
                "sector": str(r.get("hybk") or ""),
                "close": close,
                "limit_price": limit_price,
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out or None


def _safe_price(raw) -> Optional[float]:
    """push2ex 价格（厘，整数）→ 元（÷1000，2 位小数）；缺失/非法 → None。"""
    if raw is None or raw == "":
        return None
    try:
        return round(float(raw) / 1000, 2)
    except (ValueError, TypeError):
        return None


# ─────────────────────── P2-T2c：is_limit_up ───────────────────────
def is_limit_up(row: dict) -> Optional[bool]:
    """这一行今天涨停了吗。优先用「现价 == 涨停价」，缺价格字段时按制度推定。

    改写自源 is_limit_up——原 market_facts.limit_pct 依赖丢弃模块；现用内联
    _limit_pct（板别制度：主板 10% / 创业板·科创板 20% / 北交所 30% / ST 5%）。
    push2ex 单位经 _settled_pool 统一为元，abs(close-limit)<0.011 阈值成立。
    """
    close, limit = row.get("close"), row.get("limit_price")
    if close is not None and limit is not None and limit > 0:
        return abs(close - limit) < 0.011
    ret = row.get("ret")
    if ret is None:
        return None
    return ret >= _limit_pct(row.get("code", ""), row.get("name", "")) - 0.3


def _limit_pct(code: str, name: str) -> float:
    """涨停幅度（%）：北交所 30 / 创业板·科创板 20 / ST 5 / 主板 10。

    制度型判定（无网络）——is_limit_up 缺价格字段时的保守兜底。
    """
    c = str(code).zfill(6)
    if c.startswith(("8", "4")):  # 北交所
        return 30.0
    if c.startswith(("300", "301", "688", "689")):  # 创业板 / 科创板
        return 20.0
    if "ST" in str(name).upper() or "*ST" in str(name).upper():
        return 5.0
    return 10.0


def _stats_from_pool(rows: list[dict], today_codes: Optional[set]) -> dict:
    """从定稿记录算赚钱效应。样本就是记录本身，无所谓"覆盖率"。"""
    vals = [r["ret"] for r in rows if r.get("ret") is not None]
    if not vals:
        return {}
    again = [r for r in rows if r.get("ret") is not None and is_limit_up(r)]
    return {
        "available": True,
        "sample": len(vals),
        "coverage": len(vals),
        "coverage_rate": 1.0,
        "partial": False,
        "avg": round(mean(vals), 2),
        "median": round(median(vals), 2),
        "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals), 3),
        # 定稿记录里有涨停价，直接判"今天又封住了没"，比比对今日池子更可靠
        "limit_up_again_rate": round(len(again) / len(vals), 3),
        "source": "settled",
    }


# ─────────────────────── P2-T1a：money_effect ───────────────────────
def money_effect(date: str, prev: Optional[str] = None) -> dict:
    """赚钱效应：昨日涨停股在目标日的表现。先用定稿记录（任何历史日期都算得出），
    拿不到才退回实时行情。

    aggregate 口径——无个股名（守 market.py:166 零个股名契约），可进 emotion 层。
    """
    prev = prev or _prev_date(date)
    rows = _settled_pool(date)
    if rows:
        stats = _stats_from_pool(rows, None)
        if stats:
            return {**stats, "prev_date": prev}

    ok, why = live_quotes_are_close_of(date)
    if not ok:
        return {"available": False, "reason": why}
    if not prev:
        return {"available": False, "reason": "取不到前一交易日"}
    prev_zt = _zt_pool(prev)
    if prev_zt is None:
        return {"available": False, "reason": f"{prev} 涨停池取数失败"}

    codes = list(_pool_codes(prev_zt))
    if not codes:
        return {"available": False, "reason": f"{prev} 涨停池为空"}
    today_zt = _zt_pool(date)
    today_codes = _pool_codes(today_zt) if today_zt is not None else None
    pct = batch_pct(codes)
    vals = [v for v in pct.values() if v is not None]
    cov = _coverage(vals, len(codes))
    if not vals:
        return {"available": False, "reason": "批量行情全部取数失败", **cov}
    if cov["coverage_rate"] is not None and cov["coverage_rate"] < _COVERAGE_MIN:
        return {"available": False,
                "reason": f"批量行情只取到 {len(vals)}/{len(codes)} 只"
                          f"（{cov['coverage_rate']:.0%}），样本不足以代表全体",
                **cov}
    return {
        "available": True,
        "prev_date": prev,
        **cov,
        "avg": round(mean(vals), 2),
        "median": round(median(vals), 2),
        "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals), 3),
        # 涨停池取不到时宁可给 None 也不用涨幅阈值糊弄（阈值会高估）
        "limit_up_again_rate": (
            round(sum(1 for c in pct if c in today_codes) / len(vals), 3)
            if today_codes is not None else None
        ),
    }


# ─────────────────────── P2-T1b：consec_premium（分层）───────────────────────
def consec_premium(date: str, prev: Optional[str] = None) -> dict:
    """连板溢价（aggregate）：昨日 2 板以上个股在目标日的平均涨幅 = 高标承接度。

    aggregate 口径——无个股名，可进 emotion 层；按股明细走 consec_premium_detail
    独立路由（带个股名，不进 AI context，守 market.py:166 零个股名契约）。
    """
    prev = prev or _prev_date(date)
    rows = _settled_pool(date)
    if rows:
        hi = [r for r in rows
              if (r.get("prev_boards") or 0) >= 2 and r.get("ret") is not None]
        if hi:
            vals = [r["ret"] for r in hi]
            return {"available": True, "prev_date": prev, "source": "settled",
                    "sample": len(vals), "coverage": len(vals),
                    "coverage_rate": 1.0, "partial": False,
                    "avg": round(mean(vals), 2), "median": round(median(vals), 2),
                    "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals), 3)}

    ok, why = live_quotes_are_close_of(date)
    if not ok:
        return {"available": False, "reason": why}
    if not prev:
        return {"available": False, "reason": "取不到前一交易日"}
    prev_zt = _zt_pool(prev)
    if prev_zt is None:
        return {"available": False, "reason": f"{prev} 涨停池取数失败"}

    codes = [s["code"] for s in _ladder_by_boards(prev_zt) if s["boards"] >= 2]
    if not codes:
        return {"available": False, "reason": f"{prev} 无 2 板以上个股"}
    pct = batch_pct(codes)
    vals = [v for v in pct.values() if v is not None]
    cov = _coverage(vals, len(codes))
    if not vals:
        return {"available": False, "reason": "批量行情全部取数失败", **cov}
    if cov["coverage_rate"] is not None and cov["coverage_rate"] < _COVERAGE_MIN:
        return {"available": False,
                "reason": f"批量行情只取到 {len(vals)}/{len(codes)} 只"
                          f"（{cov['coverage_rate']:.0%}），样本不足以代表高标承接度",
                **cov}
    return {
        "available": True,
        "prev_date": prev,
        **cov,
        "avg": round(mean(vals), 2),
        "median": round(median(vals), 2),
        "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals), 3),
    }


def consec_premium_detail(date: str, prev: Optional[str] = None) -> dict:
    """连板溢价**按股明细**（spec §2 分层要求）：昨日 2 板以上个股在 date 的逐只表现。

    ⚠️ 带个股 code/name —— 走独立路由，**不进 AI context / journal 盖章**
    （守 market.py:166 零个股名契约 + 双源规则）。aggregate 口径见 consec_premium()。

    返结构化结果（不静默吞错——取数失败返 available=False+reason，与 aggregate 失败语义一致）：
      {available: bool, reason?: str, prev_date?: str, count: int, detail: [{code,name,prev_boards,ret}]}
    """
    prev = prev or _prev_date(date)
    rows = _settled_pool(date)
    if rows is None:
        # 源断（push2ex 限流/熔断/JSON 错）→ 不伪装成"无 2 板"（守"绝不静默吞错"）
        return {"available": False,
                "reason": "定稿记录取数失败（push2ex 源断或非交易日）",
                "prev_date": prev, "count": 0, "detail": []}
    detail = [
        {"code": r["code"], "name": r["name"],
         "prev_boards": r.get("prev_boards"), "ret": r.get("ret")}
        for r in rows
        if (r.get("prev_boards") or 0) >= 2 and r.get("ret") is not None
    ]
    return {"available": True, "prev_date": prev,
            "count": len(detail), "detail": detail}


def _prev_date(date: str) -> Optional[str]:
    """前一交易日（YYYY-MM-DD）；取不到返 None。vr_paths.prev_trading_date 返 date 对象。"""
    try:
        return prev_trading_date(_parse_date(date)).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _parse_date(date: str):
    import datetime
    return datetime.datetime.strptime(date, "%Y-%m-%d").date()


# ─────────────────────── day_summary / cycle_position ───────────────────────
_SUMMARY_SCHEMA = 1
_SUMMARY_SOURCE = "em_zt_topic_pool"  # 改写自源 "akshare_zt_pool"（数据源已换）


def _summary_cache_dir() -> str:
    """缓存目录经 vr_paths.resolve_data_dir()（不硬编码 ~/.duanxian-agents）。"""
    return str(resolve_data_dir() / "zt_summary")


def _summarize(zt: dict) -> Optional[dict]:
    """把一天的涨停池压成三个原始读数（都不依赖行情，任意历史日可算）。"""
    rows = zt.get("zt")
    if not rows:
        return None
    n_zt = len(rows)
    n_zb = int(zt.get("zb_count", 0) or 0)
    hc = int(zt.get("highest_consec", 0) or 0)
    br = (n_zb / (n_zb + n_zt)) if (n_zb + n_zt) else None
    return {"limit_up": n_zt, "highest_consec": hc, "broken_rate": br}


def day_summary(date: str) -> Optional[dict]:
    """某日的情绪原始读数，历史日落盘缓存。

    改写自源 day_summary——缓存目录 ~/.duanxian-agents → resolve_data_dir()/zt_summary；
    数据源 akshare_zt_pool → em_zt_topic_pool（push2ex）；原子写复用 vibe_astock_util。
    """
    is_past = is_settled(date)
    path = os.path.join(_summary_cache_dir(), f"{date}.json")
    if is_past and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                env = json.load(fh)
            # 版本 / 数据源 / 日期三者都要对得上才认（防文件名错拷冒充别天）
            if (isinstance(env, dict)
                    and env.get("schema") == _SUMMARY_SCHEMA
                    and env.get("source") == _SUMMARY_SOURCE
                    and env.get("date") == date
                    and isinstance(env.get("summary"), dict)):
                return env["summary"]
        except Exception:  # noqa: BLE001  缓存坏了就当没有，重新取
            pass

    zt = _zt_pool(date)
    s = _summarize(zt) if zt is not None else None
    if s and is_past:
        atomic_write_json(
            path,
            {"schema": _SUMMARY_SCHEMA, "source": _SUMMARY_SOURCE,
             "date": date, "summary": s},
        )
    return s


def _minmax(vals: list[float]) -> list[float]:
    """窗口内归一化到 0~1；全等时一律给 0.5（避免除零，也避免假装有差异）。"""
    lo, hi = min(vals), max(vals)
    return [0.5] * len(vals) if hi == lo else [(v - lo) / (hi - lo) for v in vals]


def _recent_trend(scores: list[float], eps: float = 0.03) -> str:
    """最近的走向——只看尾部斜率，和"相对窗口低点的位置"是两回事。"""
    if len(scores) < 3:
        return "样本不足"
    d1, d2 = scores[-1] - scores[-2], scores[-2] - scores[-3]
    if d1 > eps and d2 > eps:
        return "连续两日走强"
    if d1 < -eps and d2 < -eps:
        return "连续两日转弱"
    if d1 > eps:
        return "今日走强"
    if d1 < -eps:
        return "今日转弱"
    return "基本走平"


def cycle_position(date: str, lookback: int = 10) -> dict:
    """情绪周期位置：这波情绪从哪天启动、今天是第几天。

    ⚠️ 双源规则（audit §2.2）：作 STIPhase 展示层补充，**不进 AI context、
    不进 journal 盖章**——堵住它悄悄变成第二事实源。前端同屏须标注口径差异
    或主辅关系（STIPhase=主，cycle_position=辅）。
    """
    dates = trade_dates_ending_at(date, lookback)
    if not dates:  # 交易日历取不到时保住目标日
        dates = [date]
    if len(dates) < 3:
        return {"available": False, "reason": "可用交易日不足 3 天，无法定位周期"}

    series = []
    for d in dates:
        s = day_summary(d)
        if s:
            series.append({"date": d, **s})
    if len(series) < 3:
        return {"available": False, "reason": f"涨停池可用天数不足（{len(series)}/3）"}

    # 炸板率"越高越冷"取反后再平均——三项加起来才都指向同一方向。
    n_zt = _minmax([float(s["limit_up"]) for s in series])
    n_hc = _minmax([float(s["highest_consec"]) for s in series])
    brs = [s["broken_rate"] for s in series]
    known = [b for b in brs if b is not None]
    fill = sum(known) / len(known) if known else 0.5
    n_br = _minmax([float(b if b is not None else fill) for b in brs])

    for i, s in enumerate(series):
        s["score"] = round((n_zt[i] + n_hc[i] + (1 - n_br[i])) / 3, 3)

    trough = min(series, key=lambda s: s["score"])
    trough_idx = [s["date"] for s in series].index(trough["date"])
    day_n = len(series) - trough_idx
    return {
        "available": True,
        "window": len(series),
        "trough_date": trough["date"],
        "trough_score": trough["score"],
        "current_score": series[-1]["score"],
        "day_n": day_n,
        "rising": series[-1]["score"] > trough["score"],
        "trend": _recent_trend([s["score"] for s in series]),
        "pctile": (round((series[-1]["score"] - trough["score"])
                         / (max(s["score"] for s in series) - trough["score"]), 3)
                   if max(s["score"] for s in series) > trough["score"] else None),
        "series": series,
    }


# ─────────────────────── P2-T1d：build_metrics / render_metrics ───────────────────────
def build_metrics(date: str, with_cycle: bool = True) -> dict:
    """派生指标一起算（共用同一前一交易日 + 涨停池缓存，少查很多次）。

    §1.4 范围冻结：只含 3 个新指标（money_effect/consec_premium/cycle）。
    promotion/ladder_gap 不在此——market._emotion 已有，参照不移植（audit §2.1）。
    `with_cycle=False` 可跳过周期位置（AI 消费须用 False——双源规则，cycle 不进 AI）。
    """
    prev = _prev_date(date)
    out: dict = {
        "date": date,
        "prev_date": prev,
        "money_effect": money_effect(date, prev),
        "consec_premium": consec_premium(date, prev),
    }
    if with_cycle:
        out["cycle"] = cycle_position(date)
    return out


def _pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.0%}"


def _cov_note(d: dict) -> str:
    """样本不全时的警示后缀。覆盖率是"这个数字信不信得过"的前提。"""
    if not d.get("partial"):
        return ""
    exp, got = d.get("expected_sample"), d.get("sample")
    return f"｜⚠️样本不全：仅取到 {got}/{exp}，结论按部分样本看"


def render_metrics(m: dict) -> str:
    """渲染成文本块。不可用的部分如实说明原因。

    §1.4 冻结：渲染 3 个新指标段（赚钱效应/连板溢价/情绪周期）。promotion/ladder_gap
    段不在此（market._emotion 已有）。AI 消费须先 build_metrics(with_cycle=False)。
    """
    date, prev = m.get("date", ""), m.get("prev_date") or "—"
    lines = [f"[派生情绪指标 {date}｜对照前一交易日 {prev}]"]

    me = m.get("money_effect", {})
    if me.get("available"):
        lines.append(
            f"· 赚钱效应：{prev} 涨停 {me['sample']} 家，在 {date} 平均 {me['avg']:+.2f}%、"
            f"中位 {me['median']:+.2f}%；翻红率 {_pct(me['positive_rate'])}、"
            f"再度涨停 {_pct(me['limit_up_again_rate'])}" + _cov_note(me)
        )
    else:
        lines.append(f"· 赚钱效应：不可用（{me.get('reason', '未知')}）")

    cp = m.get("consec_premium", {})
    if cp.get("available"):
        lines.append(
            f"· 连板溢价（承接度）：{prev} 的 {cp['sample']} 只 2 板以上个股，"
            f"在 {date} 平均 {cp['avg']:+.2f}%、中位 {cp['median']:+.2f}%，"
            f"翻红率 {_pct(cp['positive_rate'])}" + _cov_note(cp)
        )
    else:
        lines.append(f"· 连板溢价：不可用（{cp.get('reason', '未知')}）")

    cy = m.get("cycle", {})
    if cy.get("available"):
        pctile = cy.get("pctile")
        pos = f"位于十日区间 {pctile:.0%} 分位" if isinstance(pctile, (int, float)) else "分位未知"
        lines.append(
            f"· 情绪周期（⚠️ 这是十日窗口内的**相对**读数，没有绝对含义）："
            f"窗口最低点在 {cy['trough_date']}（{cy['trough_score']}），今天距它第 {cy['day_n']} 天；"
            f"当前相对分 {cy['current_score']}，{pos}，最近走向：**{cy.get('trend', '未知')}**。"
            f"⚠️「距低点第 N 天」和「正在往上走」是两件事，别混为一谈"
        )
    elif cy:
        lines.append(f"· 情绪周期：不可用（{cy.get('reason', '未知')}）")

    return "\n".join(lines)


__all__ = [
    "batch_pct",
    "money_effect",
    "consec_premium",
    "consec_premium_detail",
    "cycle_position",
    "build_metrics",
    "render_metrics",
    "day_summary",
    "is_limit_up",
]
