# -*- coding: utf-8 -*-
"""S172 A 臂 floor——ETF 512890 红利低波取数 + 跟踪误差。

spec: specs/S172-红利低波指数复制臂/spec.md（R1-R3）。
plan: specs/S172-红利低波指数复制臂/plan.md（§2.1）。

数据源（akshare，惰性 import，调用间 sleep≥2s 惯例）：
  - fund_etf_spot_em()                → ETF 512890 实时行情（R1）
  - fund_etf_hist_em(adjust='qfq')     → ETF 历史复权净值（R3 ETF 端）
  - index_zh_a_hist()                  → 930955 指数历史（R3 index 端）
  - index_stock_cons_weight_csindex()  → 930955 published 成分权重（R2，仅对比非复制）

防封：fund_etf_spot_em / fund_etf_hist_em / index_zh_a_hist 走 push2delay
（东财延时镜像，ut 内嵌 akshare params，非 push2 裸调）。仍 sleep≥2s 惯例。
index_stock_cons_weight_csindex 走 csindex.com.cn（非东财，无防封问题）。

取数失败诚实降级返空（akshare_src chip_distribution 模式），不臆造。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

_LOGGER = logging.getLogger("vibe-research")

#: 默认跟踪误差窗口（交易日数）：1月/3月/6月/12月
_DEFAULT_WINDOWS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}

#: 年化因子（A 股 ~252 交易日/年）
_ANNUAL_FACTOR = 252


def _ak():
    """惰性 import akshare（akshare_src 模式，缺失 raise DependencyMissing）。"""
    try:
        import akshare as ak
        return ak
    except ImportError as e:
        from data.sources._common import DependencyMissing
        raise DependencyMissing("akshare 未安装：pip install akshare") from e


def _to_float(v) -> float | None:
    """安全转 float，失败返 None（akshare 数据清洗，cyq _to_float 模式）。"""
    if v is None or v == "" or v == "-" or v == "--":
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# R1: ETF 512890 实时行情
# ---------------------------------------------------------------------------

def fetch_etf_quote(code: str = "512890") -> dict:
    """取 ETF 实时行情（fund_etf_spot_em 筛 code → dict）。

    返回 {code, name, price, change, change_pct, volume, amount}，取数失败返 {}。
    """
    ak = _ak()
    try:
        df = ak.fund_etf_spot_em()
    except Exception as e:
        _LOGGER.warning("fetch_etf_quote(%s) fund_etf_spot_em 失败: %s", code, e)
        return {}
    if df is None or df.empty:
        return {}

    row = df[df["代码"].astype(str) == code]
    if row.empty:
        _LOGGER.warning("fetch_etf_quote(%s) 未在 ETF spot 找到该代码", code)
        return {}

    r = row.iloc[0]
    return {
        "code": code,
        "name": str(r.get("名称", "")),
        "price": _to_float(r.get("最新价")),
        "change": _to_float(r.get("涨跌额")),
        "change_pct": _to_float(r.get("涨跌幅")),
        "volume": _to_float(r.get("成交量")),
        "amount": _to_float(r.get("成交额")),
    }


# ---------------------------------------------------------------------------
# R2: 930955 published 成分权重
# ---------------------------------------------------------------------------

def fetch_index_cons_weight(index: str = "930955") -> list[dict]:
    """取指数 published 成分 + 权重（index_stock_cons_weight_csindex → list[dict]）。

    仅用于跟踪对比，非复制持仓。返回 [{code, name, weight}]，失败返 []。
    """
    ak = _ak()
    try:
        df = ak.index_stock_cons_weight_csindex(symbol=index)
    except Exception as e:
        _LOGGER.warning("fetch_index_cons_weight(%s) 失败: %s", index, e)
        return []
    if df is None or df.empty:
        return []

    out: list[dict] = []
    for _, r in df.iterrows():
        w = _to_float(r.get("权重"))
        out.append({
            "code": str(r.get("成分券代码", "")).zfill(6),
            "name": str(r.get("成分券名称", "")),
            "weight": w if w is not None else 0.0,
        })
    return out


# ---------------------------------------------------------------------------
# R3: 跟踪误差（ETF 历史收益 vs 指数历史收益）
# ---------------------------------------------------------------------------

def _parse_daily_returns(df, date_col: str = "日期", close_col: str = "收盘") -> list[dict]:
    """通用：akshare 历史 DataFrame → [{date, close, ret}] 按日期升序。

    ret = 前日 close → 当日 close 的涨跌幅（pct change），首条 ret=0.0。
    """
    import math
    if df is None or df.empty:
        return []

    rows: list[dict] = []
    prev_close: float | None = None
    for _, r in df.iterrows():
        d = str(r.get(date_col, ""))
        close = _to_float(r.get(close_col))
        if close is None or close <= 0:
            continue
        if prev_close is not None and prev_close > 0:
            ret = (close - prev_close) / prev_close
        else:
            ret = 0.0
        rows.append({"date": d, "close": close, "ret": ret})
        prev_close = close
    return rows


def fetch_etf_hist(code: str = "512890", start: str = "", end: str = "", retries: int = 3) -> list[dict]:
    """取 ETF 历史复权净值收益（fund_etf_hist_em adjust='qfq' → [{date, close, ret}]）。

    adjust='qfq' 前复权——含分红除权调整，收益序列无跳空（spec §5.4 "ETF 净值收益（复权）"）。
    start/end 格式 YYYYMMDD，空则 akshare 默认（全量）。

    S183 重启验证发现东财 fund_etf_hist_em 端点瞬时不稳（Connection aborted, RemoteDisconnected），
    加 retries=3 次重试（0.5s 间隔）修瞬时失败。全失败返 []，bars_provider 走 baostock fallback。
    """
    import time  # noqa: PLC0415
    ak = _ak()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            df = ak.fund_etf_hist_em(symbol=code, period="daily",
                                     start_date=start or "20200101",
                                     end_date=end or datetime.now().strftime("%Y%m%d"),
                                     adjust="qfq")
            return _parse_daily_returns(df)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(0.5)
    _LOGGER.warning("fetch_etf_hist(%s) %d 次重试全失败: %s", code, retries, last_err)
    return []


def fetch_index_hist(symbol: str = "930955", start: str = "", end: str = "") -> list[dict]:
    """取指数历史日收益（index_zh_a_hist → [{date, close, ret}]）。

    930955 = 中证红利低波动指数，东财可查。start/end 格式 YYYYMMDD。
    """
    ak = _ak()
    try:
        df = ak.index_zh_a_hist(symbol=symbol, period="daily",
                                start_date=start or "20200101",
                                end_date=end or datetime.now().strftime("%Y%m%d"))
    except Exception as e:
        _LOGGER.warning("fetch_index_hist(%s) 失败: %s", symbol, e)
        return []
    return _parse_daily_returns(df)


def tracking_error_report(
    etf_code: str = "512890",
    index_code: str = "930955",
    windows: dict[str, int] | None = None,
) -> dict:
    """跟踪误差报告：ETF 净值收益 vs 指数收益，滚动窗口（R3）。

    口径（spec §5.4）：日收益序列做差 → std(diff) × sqrt(252) 年化。
    灯：绿 <1% / 黄 1-2% / 红 >2%。

    返回 {etf_code, index_code, windows: {label: {te, n, light}}, asof_date}，
    取数失败返 {etf_code, index_code, windows: {}, error: "..."}。
    """
    windows = windows or _DEFAULT_WINDOWS

    # akshare 调用间 sleep ≥ 2s 惯例（spec §5.1 防封说明）
    etf_rets = fetch_etf_hist(etf_code)
    time.sleep(2)
    idx_rets = fetch_index_hist(index_code)
    if not etf_rets or not idx_rets:
        return {"etf_code": etf_code, "index_code": index_code,
                "windows": {}, "error": "取数失败（ETF 或指数历史为空）"}

    # 对齐日期：用 date → ret 的 dict，取交集（inner join）
    etf_map = {r["date"]: r["ret"] for r in etf_rets}
    idx_map = {r["date"]: r["ret"] for r in idx_rets}
    common_dates = sorted(set(etf_map) & set(idx_map))
    if len(common_dates) < 2:
        return {"etf_code": etf_code, "index_code": index_code,
                "windows": {}, "error": "共同日期不足 2 天"}

    import math
    diffs = [etf_map[d] - idx_map[d] for d in common_dates]

    out_windows: dict[str, dict] = {}
    for label, n_days in windows.items():
        tail = diffs[-n_days:] if len(diffs) >= n_days else diffs
        n = len(tail)
        if n < 2:
            out_windows[label] = {"te": None, "n": n, "light": "insufficient"}
            continue
        mean_diff = sum(tail) / n
        variance = sum((x - mean_diff) ** 2 for x in tail) / (n - 1)
        te = math.sqrt(variance) * math.sqrt(_ANNUAL_FACTOR)
        te_pct = te * 100  # 转百分点
        if te_pct < 1.0:
            light = "green"
        elif te_pct < 2.0:
            light = "yellow"
        else:
            light = "red"
        out_windows[label] = {"te": round(te_pct, 4), "n": n, "light": light}

    return {
        "etf_code": etf_code,
        "index_code": index_code,
        "windows": out_windows,
        "asof_date": common_dates[-1],
    }
