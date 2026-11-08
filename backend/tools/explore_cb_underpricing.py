# -*- coding: utf-8 -*-
"""explore_cb_underpricing.py — 可转债信用申购 EV 实测（underpricing 全图收口）。

S243 延伸：打新(IPO)已测(explore_ipo_underpricing.py)，CB 信用申购未测。本脚本补全。
practitioner reframe 落地——散户 edge 在 underpricing 不在选股（非 selection alpha）。

数据源：
  - bond_zh_cov()：东财，1066 只在市 CB 列表（含 申购日期/中签率/上市时间/正股代码）。
    走 circuit_breaker 防封（东财端点铁律 §1.2）。
  - bond_zh_hs_cov_daily(symbol)：新浪财经（非东财），逐只拉日 K 线取上市首日 close。
    symbol 须带市场前缀 sh/sz（由正股代码派生：6→sh，余→sz）。新浪"大量抓取易封 IP"，
    故慢拉加 sleep + 连续失败熔断 + 失败时反向前缀重试。

口径：
  - 发行价 = 面值 100 元/张；信用申购最小 10 张 = 1000 元面值（零资金门槛，资金 T+0/T+1 退回）。
  - 首日涨幅 = (首日 close - 100) / 100 × 100%。
  - 中签率字段单位 = 百分数（0.004307 = 0.004307%，万分之 0.43，同 IPO 脚本约定）。
  - EV per 申购(元) = 中签率(小数) × 中签获利(元)，中签获利 = (close-100)/100 × 1000。
    零成本 → 只要首日涨幅>0，EV 即正。
  - 年期望收益(容量, 元) = 年 CB 发行数 × 平均中签率 × 平均中签获利。

断代（信用申购 2017-09 落地，2017 前为市值配售）：
  pre2017 市值配售期(<2017)：有市值机会成本，仅作历史对照
  S1 信用申购早期(2017~2020)：信用申购元年，参与者少→中签率高
  S2 CB 破发潮(2021~2023)：供给放量+转股价值回落，破发率升
  S3 当前窗口(2024+)：唯一 actionable 段

诚实框定（选择偏差）：
  bond_zh_cov() 只返回在市 CB（含近期强赎/退市），2015 前已到期退市的旧 CB 不在。
  强赎(正股涨 130%+ 触发)的 CB 多为正股强势→首日 pop 偏高→被剔除会低估首日涨幅。
  但信用申购只看首日：首日涨幅在上市日即确定，退市后命运(强赎/到期)不改变首日 EV。
  即：样本对首日 EV 的偏差方向=低估(强赎的好 CB 缺失)，正向 EV 结论反而更保守可信。
  S3(2024+) 近乎全样本(均在市)→代表性最好，为 verdict 主依据。

kill criteria：
  - bond_zh_hs_cov_daily 不可得 → blocked（实测：需 sh/sz 前缀，可得，非 blocked）
  - EV 负(首日破发率>50%) → falsified
  - EV 正但容量<100 元/年 → neutral（零成本就申，但容量极小）

§1.2 工程底线：东财走 circuit_breaker 防封；数字从数据算禁止臆造；中签率单位显式标注。
"""
from __future__ import annotations

import logging
import random
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from circuit_breaker import get_breaker

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("cb-explore")

ISSUE_PRICE = 100.0  # CB 面值/发行价 元/张
MIN_SUB_FACE = 1000  # 信用申购最小 10 张面值合计 元

SEGMENTS = [
    ("pre2017 市值配售期(<2017)", pd.Timestamp("2007-01-01"), pd.Timestamp("2016-12-31")),
    ("S1 信用申购早期(2017~2020)", pd.Timestamp("2017-01-01"), pd.Timestamp("2020-12-31")),
    ("S2 CB破发潮(2021~2023)", pd.Timestamp("2021-01-01"), pd.Timestamp("2023-12-31")),
    ("S3 当前窗口(2024+)", pd.Timestamp("2024-01-01"), pd.Timestamp("2026-12-31")),
]

# 每段抽样规模（"all"=全拉）。S3 actionable 全拉；历史段抽样控防封。
SAMPLE_SIZES = {
    "pre2017 市值配售期(<2017)": 30,
    "S1 信用申购早期(2017~2020)": 80,
    "S2 CB破发潮(2021~2023)": 80,
    "S3 当前窗口(2024+)": "all",
}

SINA_SLEEP = 0.5  # 新浪慢拉间隔秒
SINA_JITTER = 0.3  # 随机抖动上限秒
MAX_CONSEC_FAIL = 8  # 连续失败熔断阈值


def fetch_cb_list() -> pd.DataFrame:
    """拉 bond_zh_cov() 全 CB 列表（东财，走 circuit_breaker 防封）。"""
    breaker = get_breaker("eastmoney")
    if not breaker.allow_request():
        raise RuntimeError("eastmoney 熔断器 OPEN，稍后重试")
    import akshare as ak  # noqa: PLC0415

    df = ak.bond_zh_cov()
    breaker.record_success()
    return df


def sina_symbol(stock_code: str, bond_code: str) -> str:
    """由正股代码派生新浪前缀：6→sh(沪)，余→sz(深)。CB 与正股同交易所。"""
    mkt = "sh" if str(stock_code).startswith("6") else "sz"
    return f"{mkt}{bond_code}"


def flip_prefix(symbol: str) -> str:
    """反向市场前缀（失败时兜底重试）。"""
    if symbol.startswith("sh"):
        return "sz" + symbol[2:]
    if symbol.startswith("sz"):
        return "sh" + symbol[2:]
    return symbol


def fetch_first_day_close(symbol: str) -> tuple[float, str] | None:
    """拉日 K 线取首日 close。先试派生前缀，失败兜底反向前缀。返回 (close, date) 或 None。"""
    import akshare as ak  # noqa: PLC0415

    for sym in (symbol, flip_prefix(symbol)):
        try:
            daily = ak.bond_zh_hs_cov_daily(symbol=sym)
        except Exception:
            continue
        if daily is None or len(daily) == 0:
            continue
        row0 = daily.iloc[0]
        close = pd.to_numeric(row0["close"], errors="coerce")
        if pd.notna(close):
            return float(close), str(row0["date"])
    return None


def sample_segment(seg_df: pd.DataFrame, size: int | str) -> pd.DataFrame:
    """段内抽样：size='all' 全取；否则随机抽样（固定 seed 可复现）。"""
    if size == "all" or len(seg_df) <= (size if isinstance(size, int) else 0):
        return seg_df
    return seg_df.sample(n=min(size, len(seg_df)), random_state=42)


def collect_first_days(sample: pd.DataFrame) -> pd.DataFrame:
    """逐只拉首日 close（新浪慢拉+连续失败熔断）。返回附 first_close/first_date 的 df。"""
    rows = []
    consec_fail = 0
    n = len(sample)
    for i, (_, r) in enumerate(sample.iterrows(), 1):
        bond_code = str(r["债券代码"])
        sym = sina_symbol(str(r["正股代码"]), bond_code)
        time.sleep(SINA_SLEEP + random.uniform(0, SINA_JITTER))
        try:
            res = fetch_first_day_close(sym)
        except Exception as e:  # noqa: BLE001
            log.info(f"[{i}/{n}] {bond_code} {r['债券简称']} EXC {type(e).__name__}")
            res = None
        if res is None:
            consec_fail += 1
            rows.append({**r.to_dict(), "first_close": None, "first_date": None,
                         "first_gain": None, "win_profit": None})
            log.info(f"[{i}/{n}] {bond_code} {r['债券简称']} FAIL (consec={consec_fail})")
            if consec_fail >= MAX_CONSEC_FAIL:
                log.info(f"连续失败 {consec_fail} 次，触发熔断，停止本段拉取")
                break
        else:
            consec_fail = 0
            close, date = res
            gain = (close - ISSUE_PRICE) / ISSUE_PRICE * 100  # 首日涨幅 %
            win = (close - ISSUE_PRICE) / ISSUE_PRICE * MIN_SUB_FACE  # 中签获利 元
            rows.append({**r.to_dict(), "first_close": close, "first_date": date,
                         "first_gain": gain, "win_profit": win})
            if i % 20 == 0 or i == n:
                log.info(f"[{i}/{n}] {bond_code} {r['债券简称']} close={close} gain={gain:.1f}%")
    return pd.DataFrame(rows)


def seg_stats(df: pd.DataFrame, label: str, seg_start: pd.Timestamp, seg_end: pd.Timestamp,
              n_full: int) -> dict:
    """单段统计：n/首日涨幅/破发率/中签率/EV per申购/年容量。
    df=抽样(含 K 线首日)，n_full=段内全部已上市数(列表免费，用于推年发行密度)。
    中签率与首日涨幅均取抽样子集（EV 须逐只配对，故同源）；S3=all 时抽样=全段。"""
    d = df.dropna(subset=["first_gain"])  # 拉到首日的
    n_gain = len(d)
    win_sample = pd.to_numeric(df["中签率"], errors="coerce").dropna()
    if n_gain == 0:
        return {"段": label, "n_全段": n_full, "n_抽样": len(df), "n_首日": 0}
    gain = d["first_gain"]
    win = pd.to_numeric(d["中签率"], errors="coerce")
    profit = d["win_profit"]
    破发 = gain < 0
    win_dec = win / 100  # 0.004307% → 0.00004307
    ev_per_sub = (win_dec * profit).mean()  # EV per 申购(元)
    years = max((seg_end - seg_start).days / 365.25, 0.5)
    annual_cb = n_full / years  # 用全段数推年发行密度
    annual_ev = annual_cb * win_dec.mean() * profit.mean()
    exp_wins_yr = win_dec.mean() * annual_cb  # 单账户年期望中签次数
    years_per_win = round(1 / exp_wins_yr, 0) if exp_wins_yr > 0 else float("inf")
    return {
        "段": label,
        "n_全段": n_full,
        "n_抽样": len(df),
        "n_首日": n_gain,
        "首日涨幅_mean%": round(gain.mean(), 2),
        "首日涨幅_median%": round(gain.median(), 2),
        "破发率%": round(破发.mean() * 100, 1),
        "中签率_mean%(抽样)": round(win_sample.mean(), 4),
        "中签率_median%(抽样)": round(win_sample.median(), 4),
        "中签获利_mean元": round(profit.mean(), 1),
        "EV_per申购_元": round(ev_per_sub, 5),
        "年CB发行数": round(annual_cb, 0),
        "年容量_元": round(annual_ev, 2),
        "年期望中签": round(exp_wins_yr, 5),
        "每N年中1签": years_per_win,
    }


def verdict(seg_df: pd.DataFrame) -> str:
    """按 kill criteria 出 verdict（基于 S3 当前段为主，全段对照）。"""
    s3 = seg_df[seg_df["段"].str.contains("S3")]
    if len(s3) == 0 or s3.iloc[0].get("n_首日", 0) == 0:
        return "blocked(无 S3 首日数据)"
    s3r = s3.iloc[0]
    br = float(s3r["破发率%"])
    annual = float(s3r["年容量_元"])
    ev = float(s3r["EV_per申购_元"])
    ypw = float(s3r["年期望中签"])
    nper = s3r["每N年中1签"]
    if br > 50:
        return f"FALSIFIED(S3 破发率{br}%>50%，EV 负)"
    if ev > 0 and annual < 100:
        return (f"NEUTRAL(S3 EV正{ev}元/申购，首日median+{s3r['首日涨幅_median%']}%破发率{br}%，"
                f"零成本不亏；但中签率万分之{float(s3r['中签率_median%(抽样)'])*100:.2f}极低，"
                f"年期望中签{ypw}次≈每{nper}年中1签，年容量{annual}元<<100→"
                f"理论正EV的免费彩票，实操单账户基本中不到，申无成本就申但别指望收入)")
    if ev > 0 and annual >= 100:
        return f"POSITIVE(S3 EV正{ev}元/申购 且年容量{annual}元≥100)"
    return f"NEUTRAL(EV={ev} 容量={annual})"


def main() -> None:
    use_cache = "--cache" in sys.argv
    cache_path = Path(__file__).parent / "cb_first_day_cache.csv"
    # 列表始终拉取（廉价，东财单次+circuit_breaker），用于 n_full 推年发行密度
    log.info("=== 1. 拉 bond_zh_cov() 全 CB 列表（东财+circuit_breaker）===")
    df = fetch_cb_list()
    df["上市时间_dt"] = pd.to_datetime(df["上市时间"], errors="coerce")
    listed = df[df["上市时间_dt"].notna()].copy()
    log.info(f"总 {len(df)} 只，已上市(上市时间非空) {len(listed)} 只，"
             f"上市区间 {listed['上市时间_dt'].min().date()} ~ {listed['上市时间_dt'].max().date()}")

    if use_cache and cache_path.exists():
        log.info("=== --cache 模式：读缓存跳过新浪拉取 ===")
        combined = pd.read_csv(cache_path)
    else:
        log.info("\n=== 2. 分段抽样 + 逐只拉首日 close（新浪慢拉）===")
        all_seg_rows = []
        for label, start, end in SEGMENTS:
            mask = (listed["上市时间_dt"] >= start) & (listed["上市时间_dt"] <= end)
            seg = listed[mask].copy()
            size = SAMPLE_SIZES[label]
            sample = sample_segment(seg, size)
            log.info(f"\n--- {label}: 段内 {len(seg)} 只，抽样 {len(sample)} 只 ---")
            if len(sample) == 0:
                continue
            enriched = collect_first_days(sample)
            all_seg_rows.append(enriched)
        combined = pd.concat(all_seg_rows, ignore_index=True) if all_seg_rows else pd.DataFrame()
        combined.to_csv(cache_path, index=False, encoding="utf-8-sig")
        log.info(f"首日数据缓存: {cache_path}（{len(combined)} 行）")

    log.info("\n=== 3. 分段统计 ===")
    combined["上市时间_dt"] = pd.to_datetime(combined["上市时间"], errors="coerce")
    seg_rows = []
    for label, start, end in SEGMENTS:
        seg_df = combined[(combined["上市时间_dt"] >= start) & (combined["上市时间_dt"] <= end)]
        mask_full = (listed["上市时间_dt"] >= start) & (listed["上市时间_dt"] <= end)
        n_full = int(mask_full.sum())
        if len(seg_df) == 0:
            seg_rows.append({"段": label, "n_全段": n_full, "n_抽样": 0, "n_首日": 0})
            continue
        seg_rows.append(seg_stats(seg_df, label, start, end, n_full))
    seg_df_out = pd.DataFrame(seg_rows)
    print(seg_df_out.to_string(index=False))

    log.info("\n=== 4. 首日涨幅按年分布（看破发潮）===")
    g = combined.dropna(subset=["first_gain"])
    if len(g):
        yr = g["上市时间_dt"].dt.year
        dist = g.groupby(yr)["first_gain"].agg(
            ["count", "mean", "median", lambda s: round((s < 0).mean() * 100, 1)])
        dist = dist.rename(columns={"count": "n", "mean": "mean%", "median": "median%",
                                    "<lambda_0>": "破发率%"})
        print(dist.to_string())

    log.info("\n=== 5. VERDICT ===")
    v = verdict(seg_df_out)
    log.info(v)
    # 诚实盲点
    log.info("\n盲点：")
    log.info("- 样本=在市 CB（bond_zh_cov），2015 前到期退市旧 CB 缺失；强赎 CB(正股强势)缺失→"
             "首日涨幅被低估，正向 EV 结论更保守可信")
    log.info("- 信用申购 2017-09 落地，2017-01~08 仍市值配售(有成本)，S1 段含少量非信用 CB")
    log.info("- 中签率=网上中签率(散户口径)，原股东优先配售部分不计")
    log.info("- 年容量假设每只 CB 都申购且中签获利=首日收盘卖出(未计首日无法卖出的流动性)")

    # 保存
    out = Path(__file__).parent / "explore_cb_underpricing_result.txt"
    with out.open("w", encoding="utf-8") as f:
        f.write("=== CB 信用申购 EV 分段统计 ===\n")
        f.write(seg_df_out.to_string(index=False) + "\n\n")
        f.write(f"=== VERDICT ===\n{v}\n")
    log.info(f"\n结果已存: {out}")


if __name__ == "__main__":
    main()
