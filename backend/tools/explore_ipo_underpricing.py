# -*- coding: utf-8 -*-
"""explore_ipo_underpricing.py — A 股打新 underpricing 历史收益系统验证。

S243 延伸：从"筛选红线避雷"到"历史收益/EV/中签率系统验证"。
practitioner reframe 落地——散户 edge 在 underpricing 不在选股（非 selection alpha）。

数据源：akshare stock_xgsglb_em()（4036 条 2010-2026，中签率 100% 全历史）。
4 段断代（注册制改革）：
  S1 核准制黄金期（2010 ~ 2019-07-21）：23xPE+44%涨停+市值配售，制度红利已消失不可逆
  S2 注册制试点（2019-07-22 ~ 2021-09-17）：科创板开板+创业板注册制
  S3 破发潮（2021-09-18 ~ 2023-12-31）：询价新规放开定价，破发率飙升
  S4 当前政策窗口（2024-01-01 ~ ）：监管再收紧+供给坍塌，近零破发+高首日pop

诚实框定：S1-S3 测了只证历史不可交易（制度已变），S4 是唯一 actionable 段。
EV 正但政策依赖（非结构性）+ 彩票型（中签率万分之 2.8）+ 底仓有机会成本。

§1.2 工程底线：数据走 circuit_breaker 防封；数字从数据算禁止臆造；S243 红线区分度独立验证。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

# 数据路径 + 模块导入统一走 backend/（同 explore_holiday_disentangle 模式）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from circuit_breaker import get_breaker

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ipo-explore")

# 4 段断代切点（按上市日期）
SEGMENTS = [
    ("S1 核准制黄金期(2010~2019.07)", pd.Timestamp("2010-01-01"), pd.Timestamp("2019-07-21")),
    ("S2 注册制试点(2019.07~2021.09)", pd.Timestamp("2019-07-22"), pd.Timestamp("2021-09-17")),
    ("S3 破发潮(2021.09~2023.12)", pd.Timestamp("2021-09-18"), pd.Timestamp("2023-12-31")),
    ("S4 当前政策窗口(2024+)", pd.Timestamp("2024-01-01"), pd.Timestamp("2026-12-31")),
]


def fetch_ipo_history() -> pd.DataFrame:
    """拉全历史 IPO 数据（走 circuit_breaker 防封）。"""
    breaker = get_breaker("eastmoney")
    if not breaker.allow_request():
        raise RuntimeError("eastmoney 熔断器 OPEN，稍后重试")
    import akshare as ak  # noqa: PLC0415
    df = ak.stock_xgsglb_em()
    breaker.record_success()
    return df


def enrich_board(df: pd.DataFrame) -> pd.DataFrame:
    """板块补齐——'板块'列仅 3 值（非科创板/科创板/北交所）不细标创业板，
    用股票代码前缀补齐：688=科创板 / 300+301=创业板 / 60x+00x=主板 / 8+4+920=北交所。"""
    def board_fine(code: str) -> str:
        c = str(code)
        if c.startswith("688"):
            return "科创板"
        if c.startswith(("300", "301")):
            return "创业板"
        if c.startswith(("8", "4", "920")):
            return "北交所"
        if c.startswith(("60", "00")):
            return "主板"
        return "其他"
    df = df.copy()
    df["board_fine"] = df["股票代码"].apply(board_fine)
    return df


def parse_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """数值字段清洗：涨幅/中签率/发行市盈率/行业市盈率/每中一签获利/顶格申购需配市值。"""
    df = df.copy()
    # 涨幅：可能是 "待上市" 字符串或 % 字符串，强制 numeric
    df["涨幅"] = pd.to_numeric(df["涨幅"], errors="coerce")
    # 中签率：0.028361 形式 = 0.028%（万分之 2.8）
    df["中签率"] = pd.to_numeric(df["中签率"], errors="coerce")
    df["发行市盈率"] = pd.to_numeric(df["发行市盈率"], errors="coerce")
    df["行业市盈率"] = pd.to_numeric(df["行业市盈率"], errors="coerce")
    df["每中一签获利"] = pd.to_numeric(df["每中一签获利"], errors="coerce")
    df["顶格申购需配市值"] = pd.to_numeric(df["顶格申购需配市值"], errors="coerce")
    df["发行价格"] = pd.to_numeric(df["发行价格"], errors="coerce")
    df["上市日期"] = pd.to_datetime(df["上市日期"], errors="coerce")
    # PE ratio（S243 红线核心：发行PE/行业PE）
    df["pe_ratio"] = df["发行市盈率"] / df["行业市盈率"].replace(0, pd.NA)
    return df


def seg_stats(df: pd.DataFrame, label: str) -> dict:
    """单段统计：n / 中签率 / 首日涨幅 / 破发率 / 每签获利 / EV per 申购。"""
    d = df.dropna(subset=["涨幅"])  # 去待上市
    n = len(d)
    if n == 0:
        return {"段": label, "n": 0}
    涨幅 = d["涨幅"]
    中签率 = d["中签率"].dropna()
    破发 = 涨幅 < 0
    每签 = d["每中一签获利"].dropna()
    # EV per 申购（散户口径期望收益率%）= 中签率% × 涨幅% / 100
    # 中签率字段 0.028 = 0.028%（万分之 0.28），涨幅字段 251 = 251%
    ev_per_sub = (中签率 / 100 * 涨幅.reindex(中签率.index)).mean()
    return {
        "段": label,
        "n": n,
        "中签率_mean%": round(中签率.mean(), 4),
        "中签率_median%": round(中签率.median(), 4),
        "首日涨幅_mean%": round(涨幅.mean(), 1),
        "首日涨幅_median%": round(涨幅.median(), 1),
        "破发率%": round(破发.mean() * 100, 2),
        "每签获利_mean万": round(每签.mean() / 10000, 2),
        "每签获利_median万": round(每签.median() / 10000, 2),
        "EV_per申购%": round(ev_per_sub, 5),
    }


def pe_layer_stats(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """PE 分层验 S243 红线区分度：>1.5 高溢价🔴 / 1.0-1.5 中间 / <1.0 折价🟢。
    看各层破发率 + 首日涨幅有无区分度（红线是否 inert）。"""
    d = df.dropna(subset=["涨幅", "pe_ratio"]).copy()
    if len(d) == 0:
        return pd.DataFrame()
    d["PE层"] = pd.cut(
        d["pe_ratio"],
        bins=[-float("inf"), 1.0, 1.5, float("inf")],
        labels=["<1.0折价🟢", "1.0-1.5中间", ">1.5高溢价🔴"],
    )
    rows = []
    for layer, g in d.groupby("PE层", observed=True):
        if len(g) == 0:
            continue
        rows.append({
            "段": label, "PE层": layer, "n": len(g),
            "破发率%": round((g["涨幅"] < 0).mean() * 100, 1),
            "首日涨幅_median%": round(g["涨幅"].median(), 1),
            "每签获利_median万": round(g["每中一签获利"].median() / 10000, 2),
        })
    return pd.DataFrame(rows)


def board_layer_stats(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """板分层：主板/创业板/科创板/北交所 破发率+涨幅差异（2022破发潮主板0%/科创板37.4%/北交所57.8%）。"""
    d = df.dropna(subset=["涨幅"]).copy()
    if len(d) == 0:
        return pd.DataFrame()
    rows = []
    for board, g in d.groupby("board_fine"):
        rows.append({
            "段": label, "板": board, "n": len(g),
            "破发率%": round((g["涨幅"] < 0).mean() * 100, 1),
            "首日涨幅_median%": round(g["涨幅"].median(), 1),
            "中签率_median%": round(g["中签率"].median(), 4),
        })
    return pd.DataFrame(rows).sort_values("n", ascending=False)


def yield_by_cap(df_s4: pd.DataFrame) -> pd.DataFrame:
    """S4 当前段 yield-by-cap 估算（简化口径，诚实标注假设）。
    假设：均匀申购所有新股，沪深各半，配号=市值/1万(沪)或/5千(深)。
    年期望中签 = 中签率 × 年配号数；年收益 = × 每签获利。
    ⚠ 未考虑单只股申购上限封顶（申购上限字段，股数），实际 yield 略低于估算。
    ⚠ 顶格申购需配市值字段=申购上限×发行价（总金额），非市值配号阈值，不用于 cap 限制。"""
    d = df_s4.dropna(subset=["涨幅", "中签率", "每中一签获利"]).copy()
    if len(d) == 0:
        return pd.DataFrame()
    n_years = (d["上市日期"].max() - d["上市日期"].min()).days / 365.25
    n_per_year = len(d) / max(n_years, 1)
    avg_win = d["每中一签获利"].mean()
    avg_rate = d["中签率"].mean() / 100  # 转小数（0.028% → 0.00028）
    rows = []
    for cap_wan in [20, 50, 100, 500]:
        cap = cap_wan * 10000
        # 沪每 1 万 1 配号，深每 5 千 1 配号 → 深 2 倍配号；沪深各半
        slots_per_sub = (cap / 2 / 10000) + (cap / 2 / 5000)
        exp_win_per_year = avg_rate * slots_per_sub * n_per_year
        exp_income = exp_win_per_year * avg_win
        rows.append({
            "市值档(万)": cap_wan,
            "年申购数": round(n_per_year, 0),
            "每申购配号": round(slots_per_sub, 1),
            "年期望中签": round(exp_win_per_year, 3),
            "年期望收益(元)": round(exp_income, 0),
            "年化yield%": round(exp_income / (cap_wan * 10000) * 100, 2),
            "note": "几年可能打不中" if exp_win_per_year < 1 else "",
        })
    return pd.DataFrame(rows)


def main() -> None:
    log.info("=== 拉取 IPO 全历史 ===")
    df = fetch_ipo_history()
    log.info(f"总行数: {len(df)}，上市日期: {df['上市日期'].min()} ~ {df['上市日期'].max()}")

    df = enrich_board(df)
    df = parse_numeric(df)

    # 1. 全样本 board_fine 分布（核对板块补齐）
    log.info("\n=== 板块补齐分布 ===")
    print(df["board_fine"].value_counts().to_string())

    # 2. 4 段断代统计
    log.info("\n=== 4 段断代统计（每段 n/中签率/首日涨幅/破发率/每签获利/EV）===")
    seg_rows = []
    for label, start, end in SEGMENTS:
        mask = (df["上市日期"] >= start) & (df["上市日期"] <= end)
        seg_rows.append(seg_stats(df[mask], label))
    seg_df = pd.DataFrame(seg_rows)
    print(seg_df.to_string(index=False))

    # 3. PE 分层验 S243 红线（每段）
    log.info("\n=== S243 红线 PE 分层区分度（>1.5高溢价🔴 / 1.0-1.5 / <1.0折价🟢）===")
    pe_frames = []
    for label, start, end in SEGMENTS:
        mask = (df["上市日期"] >= start) & (df["上市日期"] <= end)
        pe_frames.append(pe_layer_stats(df[mask], label))
    pe_df = pd.concat([f for f in pe_frames if len(f)], ignore_index=True)
    print(pe_df.to_string(index=False))

    # 4. 板分层（S3 破发潮 + S4 当前，看板差异）
    log.info("\n=== 板分层（S3 破发潮 + S4 当前）===")
    for label, start, end in SEGMENTS:
        if "S3" not in label and "S4" not in label:
            continue
        mask = (df["上市日期"] >= start) & (df["上市日期"] <= end)
        bdf = board_layer_stats(df[mask], label)
        if len(bdf):
            print(bdf.to_string(index=False))
            print()

    # 5. S4 yield-by-cap
    log.info("\n=== S4 当前段 yield-by-cap（简化口径）===")
    s4_label, s4_start, s4_end = SEGMENTS[3]
    s4_mask = (df["上市日期"] >= s4_start) & (df["上市日期"] <= s4_end)
    ydf = yield_by_cap(df[s4_mask])
    print(ydf.to_string(index=False))

    # 6. verdict
    log.info("\n=== VERDICT ===")
    s4 = seg_df[seg_df["段"].str.contains("S4")].iloc[0]
    log.info(f"S4 当前段: n={s4['n']}, 破发率={s4['破发率%']}%, 首日涨幅median={s4['首日涨幅_median%']}%, "
             f"中签率={s4['中签率_mean%']}%, EV_per申购={s4['EV_per申购%']}%")
    # S243 红线区分度（S4 当前段 >1.5 vs <1.0 破发率差）
    s4_pe = pe_df[pe_df["段"].str.contains("S4")]
    if len(s4_pe):
        hi = s4_pe[s4_pe["PE层"].astype(str).str.contains(">1.5")]
        lo = s4_pe[s4_pe["PE层"].astype(str).str.contains("<1.0")]
        hi_br = float(hi["破发率%"].iloc[0]) if len(hi) else None
        lo_br = float(lo["破发率%"].iloc[0]) if len(lo) else None
        log.info(f"S243 红线 S4 区分度: >1.5 破发率={hi_br}% vs <1.0 破发率={lo_br}% "
                 f"{'→ INERT（当前 regime 零破发，红线不触发）' if hi_br == 0 and lo_br == 0 else '→ 有区分度'}")

    # 保存
    out = Path(__file__).parent / "explore_ipo_underpricing_result.txt"
    with out.open("w", encoding="utf-8") as f:
        f.write("=== 4 段断代统计 ===\n")
        f.write(seg_df.to_string(index=False) + "\n\n")
        f.write("=== PE 分层验 S243 红线 ===\n")
        f.write(pe_df.to_string(index=False) + "\n\n")
        f.write("=== S4 yield-by-cap ===\n")
        f.write(ydf.to_string(index=False) + "\n")
    log.info(f"\n结果已存: {out}")


if __name__ == "__main__":
    main()
