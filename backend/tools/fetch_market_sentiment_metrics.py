# -*- coding: utf-8 -*-
"""fetch_market_sentiment_metrics —— A股情绪水位诊断（透明权重，可复算）。

§44 v3 R26：情绪得分算法须透明（非黑箱）+ 权重文档化 + 脚本化，禁 AI 主观打分。

数据源（项目已有）：
- index_ohlc_cache.json: sh.000001 量能(amount) + chg
- baostock_kline_cache.db: 全市场涨跌家数
- zt_history.db: 连板高度(lbc) + 炸板(zbc) + 晋级率

指标 + 权重（文档化）：
- 量能(W1=30): 今日成交额 vs 5日均额
- 赚钱效应(W2=30): 涨跌家数比 + 炸板率 + 昨涨停晋级率
- 连板梯队(W3=25): 最高连板高度
- 衍生(W4=15): 上证 chg（北向停发2024-08，两融须em_get未接）

状态划分：0-35 冰点 / 36-70 常态 / 71-100 沸点
"""

from __future__ import annotations
import json
import sqlite3
import statistics
from pathlib import Path
from dataclasses import dataclass

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
INDEX_CACHE = DATA / "index_ohlc_cache.json"
KLINE_DB = DATA / "baostock_kline_cache.db"
ZT_DB = DATA / "zt_history.db"

# 权重（文档化，R26 透明）
W1_LIQUIDITY = 30
W2_PROFIT_EFFECT = 30
W3_LADDER = 25
W4_DERIV = 15


@dataclass(frozen=True)
class SentimentResult:
    trade_date: str
    score: int  # 0-100
    state: str  # 冰点/常态/沸点
    liquidity_score: int  # 量能分
    profit_effect_score: int  # 赚钱效应分
    ladder_score: int  # 连板梯队分
    deriv_score: int  # 衍生分
    details: dict  # 各指标原始值
    reasons: list  # 得分理由（透明）


def load_index_bars() -> list[dict]:
    with open(INDEX_CACHE) as f:
        raw = json.load(f)
    return raw.get("sh.000001", [])


def load_kline_codes() -> list[str]:
    conn = sqlite3.connect(str(KLINE_DB))
    codes = [r[0] for r in conn.execute("SELECT DISTINCT code FROM kline")]
    conn.close()
    return codes


def load_latest_zt() -> dict:
    conn = sqlite3.connect(str(ZT_DB))
    latest_date = conn.execute("SELECT MAX(date) FROM zt_history").fetchone()[0]
    rows = conn.execute("SELECT code, lbc, zbc, fbt FROM zt_history WHERE date=?", (latest_date,)).fetchall()
    conn.close()
    return {"date": latest_date, "rows": rows}


def compute_liquidity(index_bars: list[dict]) -> tuple[int, dict]:
    """量能分(0-100): 今日成交额 vs 5日均额。放量=高分，缩量=低分。"""
    if len(index_bars) < 6:
        return 50, {"reason": "数据不足"}
    last5 = index_bars[-6:]
    today_amt = last5[-1].get("amount", 0) or 0
    ma5_amt = statistics.mean([b.get("amount", 0) or 0 for b in last5[:5]])
    if ma5_amt <= 0:
        return 50, {"today_amt": today_amt, "ma5": 0}
    ratio = today_amt / ma5_amt
    # ratio > 1.3 = 放量高分；< 0.7 = 缩量低分
    if ratio >= 1.5:
        score = 90
    elif ratio >= 1.3:
        score = 75
    elif ratio >= 1.1:
        score = 60
    elif ratio >= 0.9:
        score = 45
    elif ratio >= 0.7:
        score = 30
    else:
        score = 15
    return score, {
        "today_amt_yi": round(today_amt / 1e8, 0),
        "ma5_yi": round(ma5_amt / 1e8, 0),
        "ratio": round(ratio, 3),
    }


def compute_profit_effect(index_bars: list[dict], zt: dict) -> tuple[int, dict]:
    """赚钱效应分(0-100): 涨停数(代理亢奋) + 炸板率 + 晋级率。

    注：全市场涨跌家数须遍历 5248 股 JSON（慢 30s+），commander 诊断用
    zt 涨停数 + index chg 代理，真实涨跌家数可后续 em_get 实时拉。
    """
    zt_rows = zt["rows"]
    n_zt = len(zt_rows)
    # 涨停数分级（代理市场亢奋度）：<10 冰点 / 10-30 弱 / 30-80 常态 / 80-150 亢奋 / >150 极度狂热
    if n_zt >= 150:
        up_score = 90
    elif n_zt >= 80:
        up_score = 75
    elif n_zt >= 30:
        up_score = 55
    elif n_zt >= 10:
        up_score = 35
    else:
        up_score = 15

    # 炸板率（zbc > 0 表示当日有炸板）
    zha_ban = sum(1 for r in zt_rows if (r[2] or 0) > 0)
    zha_rate = zha_ban / n_zt if zt_rows else 0
    zha_score = int((1 - zha_rate) * 100)

    # 晋级率：lbc>=2 / 全部涨停
    relay = sum(1 for r in zt_rows if (r[1] or 1) >= 2)
    relay_rate = relay / n_zt if zt_rows else 0
    relay_score = int(relay_rate * 100) if relay_rate < 0.5 else 70

    profit = int(up_score * 0.5 + zha_score * 0.25 + relay_score * 0.25)
    return profit, {"n_zt": n_zt, "zha_rate": round(zha_rate, 3), "relay_rate": round(relay_rate, 3)}


def compute_ladder(zt: dict) -> tuple[int, dict]:
    """连板梯队分(0-100): 最高连板高度。高度高=沸点。"""
    rows = zt["rows"]
    if not rows:
        return 30, {"max_lbc": 0, "reason": "无涨停"}
    max_lbc = max((r[1] or 1) for r in rows)
    # max_lbc>=7 = 沸点 90+；4-6 = 常态 60-80；2-3 = 冰点 30-50；1 = 15
    if max_lbc >= 8:
        score = 95
    elif max_lbc >= 7:
        score = 88
    elif max_lbc >= 6:
        score = 78
    elif max_lbc >= 5:
        score = 68
    elif max_lbc >= 4:
        score = 55
    elif max_lbc >= 3:
        score = 42
    elif max_lbc >= 2:
        score = 30
    else:
        score = 15
    return score, {"max_lbc": max_lbc, "total_zt": len(rows)}


def compute_deriv(index_bars: list[dict]) -> tuple[int, dict]:
    """衍生分(0-100): 上证 chg（北向停发，两融未接，先用上证 chg 代理）。"""
    if not index_bars:
        return 50, {"reason": "无数据"}
    chg = float(index_bars[-1].get("pctChg") or 0)
    # chg > 1% = 高分；< -1% = 低分
    if chg >= 2:
        score = 90
    elif chg >= 1:
        score = 75
    elif chg >= 0.3:
        score = 60
    elif chg >= -0.3:
        score = 50
    elif chg >= -1:
        score = 35
    elif chg >= -2:
        score = 20
    else:
        score = 10
    return score, {"sh_chg": round(chg, 3)}


def diagnose() -> SentimentResult:
    """主诊断函数：算4指标 → 加权总分 → 状态划分。"""
    index_bars = load_index_bars()
    zt = load_latest_zt()

    liq_s, liq_d = compute_liquidity(index_bars)
    prof_s, prof_d = compute_profit_effect(index_bars, zt)
    lad_s, lad_d = compute_ladder(zt)
    der_s, der_d = compute_deriv(index_bars)

    # 加权（文档化）
    score = int(liq_s * W1_LIQUIDITY / 100 + prof_s * W2_PROFIT_EFFECT / 100 + lad_s * W3_LADDER / 100 + der_s * W4_DERIV / 100)

    if score <= 35:
        state = "冰点"
    elif score <= 70:
        state = "常态"
    else:
        state = "沸点"

    reasons = [
        f"量能分{liq_s}({liq_d})权重{W1_LIQUIDITY}",
        f"赚钱效应分{prof_s}({prof_d})权重{W2_PROFIT_EFFECT}",
        f"连板梯队分{lad_s}({lad_d})权重{W3_LADDER}",
        f"衍生分{der_s}({der_d})权重{W4_DERIV}",
        f"加权总分{score}→{state}",
    ]

    return SentimentResult(
        trade_date=index_bars[-1]["date"] if index_bars else "",
        score=score,
        state=state,
        liquidity_score=liq_s,
        profit_effect_score=prof_s,
        ladder_score=lad_s,
        deriv_score=der_s,
        details={**liq_d, **prof_d, **lad_d, **der_d},
        reasons=reasons,
    )


if __name__ == "__main__":
    r = diagnose()
    print(f"交易日: {r.trade_date}")
    print(f"情绪得分: {r.score}/100 → {r.state}")
    print(f"\n指标分解:")
    for reason in r.reasons:
        print(f"  - {reason}")
