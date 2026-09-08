# -*- coding: utf-8 -*-
"""S171 R1 数据采集 scan_long_value_cache.py——Layer0.5-4 baostock 多年 cache。

spec: specs/S171-长线价值/spec.md（R1）。plan: plan.md（§4）。tasks: tasks.md（T2-T7）。

Layer 依赖序（非任意序——Layer1/2/3 需 stock_basic 先就绪）：
  Layer0.5 query_stock_basic code 前缀过滤 A 股 → stock_basic_type1.json（T2，供 Layer1/2/3 迭代 + 退市元数据）
  Layer1   baostock kline 多年（adjustflag=2 前复权 return 用 + adjustflag=3 不复权 PE 用，bug 1，T4）
  Layer2   baostock profit_data 多年（2016-2026×4Q，pubDate+epsTTM+roeAvg+MBRevenue+totalShare，T5）
  Layer3   query_all_stock 月末 PIT active 集 + A 股交集 + outDate 二义 + 0bars + 停牌过滤（T6）
  Layer4   benchmark HS300+ZZ500（pctChg，股息率 caveat，T7）

cache 存 .vibe-research/（VR_DATA_DIR，.gitignore，不 in git）。atomic write（tmp+os.replace）。
cache 即 checkpoint——per-batch atomic write，resume 跳过 cache 已有 code（crash 最多丢 N 股）。
re-login per N 股（BaoStock 长会话超时返空，retry once）——复用 first_board_premium_baseline +
refresh_kline_cache 的 _login/logout/re-login/retry-once/finally-logout 模式（CLAUDE.md §7 先搜后写）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from vr_paths import resolve_data_dir  # noqa: E402

DATA_DIR = resolve_data_dir()  # .vibe-research/
SCRATCH = DATA_DIR / "s171_long_value"
SCRATCH.mkdir(parents=True, exist_ok=True)

# A 股 code 前缀（baostock code 格式 sh.6XXXXXX / sz.000XXX / sz.002XXX / sz.30XXXX / sh.688XXX / bj.XXXXXX）
# 非 type=1 参数（baostock query_stock_basic 签名 (code='', code_name='')——无 type 参数，bug 2 fix）
_A_PREFIXES = ("sh.60", "sh.68", "sz.000", "sz.001", "sz.002", "sz.003", "sh.688", "bj.")

# baostock 日K 字段（repo 标准 10 字段，refresh_kline_cache.py:24 / kline_returns.py:150）
_KLINE_FIELDS = "date,open,high,low,close,volume,amount,turn,pctChg,isST"

# 2016-01-01..2026-09-03（~129 月，过 R6 60 门槛；2016+ 给 PIT earnings 4Q lookback）
_KLINE_START = "2016-01-01"
_KLINE_END = "2026-09-03"

# profit 多年：2016-2026 × Q1-Q4 = 44 季度（2018-01 rebalance 的 PIT earnings 需 2017Q3 pubDate~2017-10）
_PROFIT_YEARS = list(range(2016, 2027))  # 2016..2026 inclusive
_PROFIT_QUARTERS = (1, 2, 3, 4)

# re-login 批大小（BaoStock 长会话超时返空，每 N 股 re-login）
_RELOGIN_BATCH_KLINE = 50    # spec §Layer1 per-50（first_board_premium_baseline.py:44）
_RELOGIN_BATCH_PROFIT = 300  # profit 1-row/call 更快，re-login 间隔可大（avoid 600 re-logins）

# benchmark 指数（adjustflag=3 指数惯例——pctChg 不含分红，股息率 caveat 标注）
_BENCHMARK_CODES = ("sh.000300", "sh.000905")  # HS300 大盘 + ZZ500 中盘


def _atomic_write_json(path: Path, data) -> None:
    """atomic write（tmp+os.replace，POSIX 原子 inode swap）——防 kill 时 truncated JSON（plan §4）。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _is_a_share(code: str) -> bool:
    """code 前缀过滤 A 股股票（剔除指数/债券/ETF——query_stock_basic 返所有证券，bug 2）。"""
    return code.startswith(_A_PREFIXES)


def _bs_login() -> bool:
    """baostock login（返 True/False；error_code 是字符串 '0'=ok，getattr 防 attr 缺失）。"""
    import baostock as bs
    lg = bs.login()
    return getattr(lg, "error_code", "0") == "0"


def _bs_logout() -> None:
    """baostock logout（吞异常——teardown 不阻塞，refresh_kline_cache.py:168 同模式）。"""
    import baostock as bs
    try:
        bs.logout()
    except Exception:
        pass


def _fetch_kline_one(bs_code: str, adjustflag: str, bs) -> list[dict]:
    """baostock 日K（_KLINE_START.._KLINE_END，指定 adjustflag）。空/错返 []（re-login retry 由调用方做）。

    adjustflag='2'=前复权（return 用，含 split/dividend 经济回报）；
    '3'=不复权（PE 用——前复权调当前股本但 epsTTM 原始股本→PE 虚低，bug 1 fix）。
    row parse 复用 refresh_kline_cache._fetch_since:58-75（10 字段 float guard + ValueError/IndexError continue）。
    """
    try:
        rs = bs.query_history_k_data_plus(
            bs_code, _KLINE_FIELDS,
            start_date=_KLINE_START, end_date=_KLINE_END, adjustflag=adjustflag,
        )
    except Exception:
        return []
    if rs.error_code != "0":
        return []
    bars: list[dict] = []
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            bars.append({
                "date": d[0],
                "open": float(d[1]) if d[1] else 0.0,
                "high": float(d[2]) if d[2] else 0.0,
                "low": float(d[3]) if d[3] else 0.0,
                "close": float(d[4]) if d[4] else 0.0,
                "volume": float(d[5]) if len(d) > 5 and d[5] else 0.0,
                "amount": float(d[6]) if len(d) > 6 and d[6] else 0.0,
                "turn": float(d[7]) if len(d) > 7 and d[7] else 0.0,
                "pctChg": float(d[8]) if len(d) > 8 and d[8] else 0.0,
                "isST": d[9] if len(d) > 9 and d[9] else "0",
            })
        except (ValueError, IndexError):
            continue
    return bars


def _fetch_profit_one(bs_code: str, year: int, quarter: int, bs) -> dict | None:
    """baostock query_profit_data——1 row per (code, year, quarter)（VERIFIED LIVE）。

    返 {pubDate, statDate, roeAvg, epsTTM, MBRevenue, totalShare}（S171 字段子集）。
    缺失 quarter（新股未到/退市后）返 None，不臆造。
    fields VERIFIED: code[0] pubDate[1] statDate[2] roeAvg[3] npMargin[4] gpMargin[5]
                     netProfit[6] epsTTM[7] MBRevenue[8] totalShare[9] liqaShare[10]
    """
    try:
        rs = bs.query_profit_data(code=bs_code, year=year, quarter=quarter)
    except Exception:
        return None
    if rs.error_code != "0":
        return None
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()
        try:
            return {
                "pubDate": d[1] if len(d) > 1 else "",
                "statDate": d[2] if len(d) > 2 else "",
                "roeAvg": float(d[3]) if len(d) > 3 and d[3] else 0.0,
                "epsTTM": float(d[7]) if len(d) > 7 and d[7] else 0.0,
                "MBRevenue": float(d[8]) if len(d) > 8 and d[8] else 0.0,
                "totalShare": float(d[9]) if len(d) > 9 and d[9] else 0.0,
            }
        except (ValueError, IndexError):
            return None
    return None


def _month_end_trading_days(start: str = _KLINE_START, end: str = _KLINE_END) -> list[str]:
    """baostock query_trade_dates → 每月最后交易日（非 calendar 月末——周末/假日无 close）。T8.1。

    query_trade_dates 返日历 + is_trading_day flag（fields=['calendar_date','is_trading_day']，VERIFIED）。
    按 YYYY-MM 分组，取 is_trading=='1' 的最大 date（first_board_layer_lift.py:321 模式扩展到月末）。
    """
    import baostock as bs
    if not _bs_login():
        return []
    trading: list[str] = []
    try:
        rs = bs.query_trade_dates(start_date=start, end_date=end)
        while rs.error_code == "0" and rs.next():
            d = rs.get_row_data()  # [calendar_date, is_trading_day]
            if len(d) >= 2 and d[1] == "1":
                trading.append(d[0])
    finally:
        _bs_logout()
    by_month: dict[str, str] = {}
    for d in trading:
        m = d[:7]  # YYYY-MM
        if m not in by_month or d > by_month[m]:
            by_month[m] = d
    return sorted(by_month.values())


def _fetch_universe_pit(day: str, a_codes: set[str], bs) -> tuple[set, set]:
    """query_all_stock(day) → PIT active 集 + suspended 集。T6.1。

    fields VERIFIED LIVE = ['code','tradeStatus','code_name']（仅 3，无 outDate/ipoDate——
    退市元数据从 stock_basic_type1.json 取）。tradeStatus '1'=trading '0'=suspended（停牌 filter）。
    返所有证券（含指数/债券/ETF）→ 与 a_codes 交集过滤仅 A 股。
    PIT VERIFIED：2010-06-01 返 2159（历史 active），2024-11-18 返 5650（当前）——非当前快照。
    """
    try:
        rs = bs.query_all_stock(day=day)
    except Exception:
        return set(), set()
    if rs.error_code != "0":
        return set(), set()
    active: set[str] = set()
    suspended: set[str] = set()
    while rs.error_code == "0" and rs.next():
        d = rs.get_row_data()  # [code, tradeStatus, code_name]
        if len(d) < 2:
            continue
        code, status = d[0], d[1]
        if code not in a_codes:
            continue
        if status == "1":
            active.add(code)
        else:
            suspended.add(code)
    return active, suspended


def scan_stock_basic() -> dict:
    """Layer0.5：baostock query_stock_basic() 全表 → code 前缀过滤 A 股 → stock_basic_type1.json。

    baostock query_stock_basic(code='', code_name='') 返所有证券（含指数/债券/ETF），
    无 type 参数（spec 原 'type=1 过滤' 无效，bug 2 fix：用 code 前缀）。
    存 {code: {code_name, ipoDate, outDate, type, status}} 供 Layer1/2 迭代 + Layer3 退市元数据。
    退市股数（outDate!=""）须 vs 已知 A 股退市股总数（~300+）交叉验（bug 3 漏标率）。
    """
    import baostock as bs

    cache_path = SCRATCH / "stock_basic_type1.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_bytes())
        print(f"[S171 Layer0.5] cache hit: {len(data)} A 股")
        return data

    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        print(f"[S171 Layer0.5] baostock login fail: {lg.error_code} {lg.error_msg}")
        return {}

    rs = bs.query_stock_basic(code="")
    if rs.error_code != "0":
        print(f"[S171 Layer0.5] query_stock_basic fail: {rs.error_code} {rs.error_msg}")
        bs.logout()
        return {}

    # fields: code, code_name, ipoDate, outDate, type, status
    all_securities = []
    while rs.error_code == "0" and rs.next():
        all_securities.append(rs.get_row_data())

    a_shares = {}
    n_delisted = 0
    for row in all_securities:
        code = row[0]
        if not _is_a_share(code):
            continue
        out_date = row[3] if len(row) > 3 else ""
        if out_date:
            n_delisted += 1
        a_shares[code] = {
            "code_name": row[1],
            "ipoDate": row[2],
            "outDate": out_date,
            "type": row[4] if len(row) > 4 else "",
            "status": row[5] if len(row) > 5 else "",
        }

    _atomic_write_json(cache_path, a_shares)
    bs.logout()
    print(f"[S171 Layer0.5] {len(all_securities)} 证券 → {len(a_shares)} A 股 "
          f"（{n_delisted} 退市 outDate!=''）→ {cache_path}")
    print(f"[S171 Layer0.5] 退市股数 {n_delisted} vs 已知~300+（bug 3 漏标率交叉验）")
    return a_shares


def scan_kline_long(adjustflag: str = "both", limit: int | None = None) -> dict:
    """Layer1：baostock kline 多年（两套 adjustflag=2+3，bug 1 前复权 PE 致命 fix）。T4。

    adjustflag='2'=前复权（return 用）+ '3'=不复权（PE 用）——spec bug 1：
    前复权调历史价到当前股本但 epsTTM 原始股本→PE 虚低→成长股误入 Q1 value。
    两套 cache：baostock_kline_qfq.json（adjustflag=2）+ baostock_kline_raw.json（adjustflag=3）。

    per-_RELOGIN_BATCH_KLINE 股 re-login（BaoStock 长会话超时返空，retry once）。
    cache 即 checkpoint——per-batch atomic write，resume 跳过 cache 已有 code（crash 最多丢 N 股）。
    """
    import baostock as bs

    basics = scan_stock_basic()  # Layer0.5 先就绪（4106 A 股 + 退市元数据）
    codes = list(basics.keys())
    if limit:
        codes = codes[:limit]

    flags = ("2", "3") if adjustflag == "both" else (adjustflag,)
    out: dict[str, dict] = {}
    for flag in flags:
        suffix = "qfq" if flag == "2" else "raw"
        cache_path = SCRATCH / f"baostock_kline_{suffix}.json"
        # resume：load 已有 cache（cache 即 checkpoint，跳过 done code）
        cache: dict[str, list] = {}
        if cache_path.exists():
            cache = json.loads(cache_path.read_bytes())
        done = set(cache.keys())
        todo = [c for c in codes if c not in done]
        print(f"[S171 Layer1/{suffix}] {len(done)}/{len(codes)} done, {len(todo)} todo, adjustflag={flag}",
              flush=True)

        if not todo:
            out[flag] = cache
            continue

        if not _bs_login():
            print(f"[S171 Layer1/{suffix}] baostock login 失败")
            out[flag] = cache
            continue

        t0 = time.time()
        try:
            for i, code in enumerate(todo):
                # re-login per N 股（BaoStock 长会话超时返空）
                if i and i % _RELOGIN_BATCH_KLINE == 0:
                    _bs_logout()
                    if not _bs_login():
                        print(f"[S171 Layer1/{suffix}] re-login 失败 @ {i}, 中止（已写 {len(cache)}）")
                        break
                    el = time.time() - t0
                    print(f"[S171 Layer1/{suffix}] re-login @ {i}/{len(todo)} done={len(cache)} "
                          f"elapsed={el:.0f}s eta={el / i * (len(todo) - i):.0f}s", flush=True)

                bars = _fetch_kline_one(code, flag, bs)
                if not bars:
                    # re-login retry once（长会话超时返空，refresh_kline_cache.py:146-149 同模式）
                    if _bs_login():
                        bars = _fetch_kline_one(code, flag, bs)
                if not bars:
                    # 退市 0-bars / 停牌整段 / baostock 不覆盖——跳过不臆造（0-bars 退市 coverage 在 R2 审计）
                    continue
                cache[code] = bars

                # per-batch atomic write（cache 即 checkpoint，crash 最多丢 N 股）
                if (i + 1) % _RELOGIN_BATCH_KLINE == 0:
                    _atomic_write_json(cache_path, cache)
        finally:
            _bs_logout()

        _atomic_write_json(cache_path, cache)  # 最终写
        out[flag] = cache
        print(f"[S171 Layer1/{suffix}] done: {len(cache)}/{len(codes)} adjustflag={flag} → {cache_path}",
              flush=True)
    return out


def scan_profit_multiyear(limit: int | None = None) -> dict:
    """Layer2：baostock profit_data 多年（2016-2026×4Q，~44Q）。T5。

    query_profit_data(code, year, quarter)——1 call = 1 row（code×year×quarter，VERIFIED），
    code 须 baostock 9 位。返 pubDate+epsTTM+roeAvg+MBRevenue+totalShare。
    pubDate 是 PIT 锚点（harness 层 enforce pubDate < D 严格小于，bug 7）。

    per-_RELOGIN_BATCH_PROFIT 股 re-login（profit 1-row/call 更快，间隔可大）。
    cache 即 checkpoint（{code: {quarter_str: {pubDate, epsTTM, roeAvg, MBRevenue, totalShare}}}）。
    resume：跳过 cache 已有 code。全 44 quarter empty → re-login retry once（timeout 返空非无数据）。
    """
    import baostock as bs

    basics = scan_stock_basic()
    codes = list(basics.keys())
    if limit:
        codes = codes[:limit]

    cache_path = SCRATCH / "profit_data_multiyear.json"
    cache: dict[str, dict] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_bytes())
    done = set(cache.keys())
    todo = [c for c in codes if c not in done]
    print(f"[S171 Layer2] {len(done)}/{len(codes)} done, {len(todo)} todo", flush=True)

    if not todo:
        return cache

    if not _bs_login():
        print("[S171 Layer2] baostock login 失败")
        return cache

    t0 = time.time()
    try:
        for i, code in enumerate(todo):
            if i and i % _RELOGIN_BATCH_PROFIT == 0:
                _bs_logout()
                if not _bs_login():
                    print(f"[S171 Layer2] re-login 失败 @ {i}, 中止（已写 {len(cache)}）")
                    break
                el = time.time() - t0
                print(f"[S171 Layer2] re-login @ {i}/{len(todo)} done={len(cache)} "
                      f"elapsed={el:.0f}s eta={el / i * (len(todo) - i):.0f}s", flush=True)

            quarters = _fetch_all_quarters(code, basics[code], bs)
            # 全 empty → 可能 timeout（非无数据，pre-IPO 的 quarter 本就 empty 但不全是）
            if not quarters:
                if _bs_login():
                    quarters = _fetch_all_quarters(code, basics[code], bs)
            if quarters:
                cache[code] = quarters

            if (i + 1) % _RELOGIN_BATCH_PROFIT == 0:
                _atomic_write_json(cache_path, cache)
    finally:
        _bs_logout()

    _atomic_write_json(cache_path, cache)
    print(f"[S171 Layer2] done: {len(cache)}/{len(codes)} → {cache_path}", flush=True)
    return cache


def _fetch_all_quarters(bs_code: str, meta: dict, bs) -> dict[str, dict]:
    """取 bs_code 的全部季度 profit（2016-2026×4Q，跳过 ipoDate 前年份省 calls）。

    新股 ipoDate 后才有数据，pre-IPO year 跳过省 calls（不臆造 None）。
    """
    quarters: dict[str, dict] = {}
    ipo = meta.get("ipoDate", "2016-01-01")[:4]
    try:
        ipo_year = int(ipo)
    except ValueError:
        ipo_year = 2016
    for year in _PROFIT_YEARS:
        if year < ipo_year:
            continue
        for q in _PROFIT_QUARTERS:
            row = _fetch_profit_one(bs_code, year, q, bs)
            if row:
                quarters[f"{year}Q{q}"] = row
    return quarters


def scan_universe_monthly() -> dict:
    """Layer3：query_all_stock 月末 PIT active 集 + A 股交集 + 退市审计 + 停牌过滤。T6。

    query_all_stock(day) 返 PIT active 集（2010→2159, 2024→5650，PIT 历史非当前快照，VERIFIED）。
    fields=['code','tradeStatus','code_name']（仅 3，无 outDate/ipoDate——退市元数据从 stock_basic 取）。
    tradeStatus '1'=trading '0'=suspended（停牌 filter——universe 用 active，suspended 记录供 R2 双重剔除）。

    PIT 第一步 gate（T6.1）：抽查前 3 月 active ∩ stock_basic(outDate>D) 须非空（含即将退市股→PIT 确认）。
    query_all_stock PIT 对已退市股覆盖 INCOMPLETE（sz.000405 在 2010+2024 都缺席）→ fallback
    stock_basic 重建（ipoDate<=D AND (outDate>D OR outDate='')）在 R2 harness 层兜底，Layer3 只报 PIT gate。
    """
    import baostock as bs

    basics = scan_stock_basic()
    a_codes = {c for c in basics if _is_a_share(c)}

    cache_path = SCRATCH / "historical_universe_monthly.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_bytes())
        print(f"[S171 Layer3] cache hit: {len(data)} 月")
        return data

    month_ends = _month_end_trading_days()
    if not month_ends:
        print("[S171 Layer3] 无月末交易日（query_trade_dates 失败？）")
        return {}

    if not _bs_login():
        print("[S171 Layer3] baostock login 失败")
        return {}

    universe: dict[str, dict] = {}
    n_delist_seen = 0  # PIT gate 抽查计数（前 3 月即将退市股）
    try:
        for i, d in enumerate(month_ends):
            active, suspended = _fetch_universe_pit(d, a_codes, bs)
            universe[d] = {
                "active": sorted(active),
                "suspended": sorted(suspended),
                "n_active": len(active),
                "n_suspended": len(suspended),
            }
            # PIT gate 抽查（前 3 月）：active ∩ stock_basic(outDate>D) 须非空
            if i < 3:
                soon_delist = [c for c in active
                               if basics.get(c, {}).get("outDate", "") > d]
                n_delist_seen += len(soon_delist)
                print(f"[S171 Layer3 PIT gate] {d}: active={len(active)} "
                      f"soon_delist(outDate>D)={len(soon_delist)}", flush=True)
            if (i + 1) % 20 == 0:
                _atomic_write_json(cache_path, universe)
                print(f"[S171 Layer3] {i + 1}/{len(month_ends)} months", flush=True)
    finally:
        _bs_logout()

    _atomic_write_json(cache_path, universe)

    # 退市覆盖审计（T6.4）：退市股总数统计（0-bars 覆盖率在 R2 harness 算——需 Layer1 kline）
    delisted = {c: v for c, v in basics.items() if v.get("outDate", "")}
    print(f"[S171 Layer3] 退市股总数 {len(delisted)}（outDate!=''）——0-bars 覆盖率在 R2 harness 算")
    print(f"[S171 Layer3] PIT gate 抽查 {min(3, len(month_ends))} 月，soon_delist 总 {n_delist_seen} "
          f"({'PIT 确认' if n_delist_seen > 0 else '⚠ query_all_stock PIT 覆盖不全，R2 须 fallback stock_basic 重建'})")
    print(f"[S171 Layer3] done: {len(universe)} 月 → {cache_path}", flush=True)
    return universe


def scan_benchmark() -> dict:
    """Layer4：HS300+ZZ500 2016-2026 日K pctChg。T7。

    sh.000300（HS300 大盘）+ sh.000905（ZZ500 中盘），adjustflag='3'（指数惯例，
    index_ma20_regime_fetch.py:50 模式）。caveat 标注：pctChg 不含分红（股息率未计——
    value premium 对比须注意，spec §Layer4）。
    """
    import baostock as bs

    cache_path = SCRATCH / "benchmark_indices.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_bytes())
        print(f"[S171 Layer4] cache hit: {list(data.keys())}")
        return data

    if not _bs_login():
        print("[S171 Layer4] baostock login 失败")
        return {}

    out: dict[str, list[dict]] = {}
    try:
        for code in _BENCHMARK_CODES:
            # 指数用 date+close+pctChg（pctChg 不含分红，股息率 caveat）
            try:
                rs = bs.query_history_k_data_plus(
                    code, "date,close,pctChg",
                    start_date=_KLINE_START, end_date=_KLINE_END, adjustflag="3",
                )
            except Exception:
                print(f"[S171 Layer4] {code} exception, 跳过")
                continue
            if rs.error_code != "0":
                print(f"[S171 Layer4] {code} fail: {rs.error_code} {rs.error_msg}")
                continue
            bars: list[dict] = []
            while rs.error_code == "0" and rs.next():
                d = rs.get_row_data()
                try:
                    bars.append({
                        "date": d[0],
                        "close": float(d[1]) if d[1] else 0.0,
                        "pctChg": float(d[2]) if len(d) > 2 and d[2] else 0.0,
                    })
                except (ValueError, IndexError):
                    continue
            out[code] = bars
            print(f"[S171 Layer4] {code}: {len(bars)} bars", flush=True)
    finally:
        _bs_logout()

    _atomic_write_json(cache_path, out)
    print(f"[S171 Layer4] done: {list(out.keys())} → {cache_path}")
    print("[S171 Layer4] caveat: pctChg 不含分红（股息率未计——value premium 对比注意）")
    return out


if __name__ == "__main__":
    # 默认跑 Layer0.5（T2.1，快无依赖）。Layer1-4 通过 --layer 指定。
    # --limit 限制股数（timing 测试用，如 --limit 5）。
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--layer", default="0.5",
                   help="0.5 stock_basic / 1 kline / 2 profit / 3 universe / 4 benchmark / all")
    p.add_argument("--limit", type=int, default=None, help="限制股数（timing 测试用）")
    p.add_argument("--adjustflag", default="both", help="Layer1: both / 2 (qfq) / 3 (raw)")
    args = p.parse_args()

    if args.layer in ("0.5", "all"):
        scan_stock_basic()
    if args.layer in ("1", "all"):
        scan_kline_long(adjustflag=args.adjustflag, limit=args.limit)
    if args.layer in ("2", "all"):
        scan_profit_multiyear(limit=args.limit)
    if args.layer in ("3", "all"):
        scan_universe_monthly()
    if args.layer in ("4", "all"):
        scan_benchmark()
