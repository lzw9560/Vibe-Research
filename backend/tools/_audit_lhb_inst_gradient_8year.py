# -*- coding: utf-8 -*-
"""LHB 机构席位梯度 8 年审计（backfill R37 前置兑现）。

consecutive_relay grilling 发现资金流梯度 inst_dominant +0.405% gross 但 stop -0.286%
无显著性（best p=0.13），"LHB 仅 1 年 underpowered"是最大 blocker。
backfill 2018-2025 完成（2123 天 150 万行）——本脚本 8 年 LHB 上榜股机构席位分层。

第一步：分层统计 + 跨年分布（先验，不算次日表现）。
第二步（待做）：次日表现 T+1open→T+2close + day_paired t + Bonferroni（baostock kline N+1）。
"""
import sqlite3
from pathlib import Path
from collections import defaultdict

DATA = Path(__file__).resolve().parents[2] / ".vibe-research"
DT_DB = DATA / "dragon_tiger_history.db"

# R34 机构+外资席位关键词
INST_KEYWORDS = (
    "机构专用", "总部", "高盛", "瑞银", "股通", "摩根",
    "中信证券股份有限公司上海分公司", "国际金融",
)


def audit_inst_gradient() -> dict:
    """8 年 LHB 上榜股机构席位分层 + 跨年分布。"""
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute("""
        SELECT trade_date, security_code, dept_name, buy, net
        FROM dragon_tiger_rows
        WHERE side='buy' AND buy IS NOT NULL AND buy > 0
        ORDER BY trade_date
    """).fetchall()
    conn.close()

    # 按 (trade_date, code) 分组
    picks: dict[tuple[str, str], list[tuple[str, float, float]]] = defaultdict(list)
    for date, code, dept, buy, net in rows:
        picks[(date, code)].append((dept or "", buy or 0, net or 0))

    # 分层（grilling 口径：inst_dominant >0.5 / inst_selling net<0 / lhb_mixed 其他）
    layers: dict[str, list] = {"inst_dominant": [], "lhb_mixed": [], "inst_selling": []}
    for (date, code), seats in picks.items():
        total_buy = sum(s[1] for s in seats)
        if total_buy <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        inst_net_pct = inst_buy / total_buy
        net_total = sum(s[2] for s in seats)
        if inst_net_pct > 0.5:
            layers["inst_dominant"].append((date, code, inst_net_pct, net_total))
        elif net_total < 0:
            layers["inst_selling"].append((date, code, inst_net_pct, net_total))
        else:
            layers["lhb_mixed"].append((date, code, inst_net_pct, net_total))

    print(f"=== 8 年 LHB 机构席位梯度（{rows[0][0]} ~ {rows[-1][0]}）===")
    print(f"总 LHB 上榜 (date, code): {len(picks)}")
    for layer, items in layers.items():
        pct = len(items) / len(picks) * 100 if picks else 0
        print(f"  {layer}: {len(items)} picks ({pct:.1f}%)")
        if items:
            inst_pcts = [x[2] for x in items]
            print(f"    inst_net_pct mean={sum(inst_pcts)/len(inst_pcts):.3f}")

    # 跨年分布
    print(f"\n=== 跨年分布（看生态变迁）===")
    for layer, items in layers.items():
        by_year: dict[str, int] = defaultdict(int)
        for date, code, _, _ in items:
            by_year[date[:4]] += 1
        print(f"  {layer}: {dict(sorted(by_year.items()))}")

    # 跨年 inst_dominant 占比趋势（验证"拉萨退守机构外资主导"R34）
    print(f"\n=== inst_dominant 年度占比趋势（R34 机构化验证）===")
    year_total: dict[str, int] = defaultdict(int)
    year_inst: dict[str, int] = defaultdict(int)
    for (date, code), seats in picks.items():
        total_buy = sum(s[1] for s in seats)
        if total_buy <= 0:
            continue
        inst_buy = sum(s[1] for s in seats if any(k in s[0] for k in INST_KEYWORDS))
        year_total[date[:4]] += 1
        if inst_buy / total_buy > 0.5:
            year_inst[date[:4]] += 1
    for year in sorted(year_total):
        print(f"  {year}: inst_dominant {year_inst[year]}/{year_total[year]} = {year_inst[year]/year_total[year]*100:.1f}%")

    return {"layers": layers, "n_picks": len(picks)}


if __name__ == "__main__":
    audit_inst_gradient()
