# -*- coding: utf-8 -*-
"""short_term_tactics_filter —— 短线战法排雷过滤器（S234）。

借鉴用户给的安全审查 JSON 模板（is_passed/risk_level/hit_rules/reason/safe_action）
+ 双层漏斗（财务硬过滤 sound + 情绪因子 标 falsified 不假装 alpha）
+ 战法矩阵（战法1早盘弱转强 9:25 / 战法2尾盘趋势锁定 14:50）
+ 防御规则（量化尾盘偷袭/虚假封单）。

§44 v3 R30：每因子旁标 verdict（诚实标注 falsified，不藏）
§44 v3 R27：买入可实现性 gate（一字涨停不可买，待 T+1 open 数据）
§1.2 工程底线：不编主力意图（只基于可观测量价/席位，"主力意图"话术剔除）

数据源（复用现有，不重造）：
- baostock_kline_cache.db: 5248 股 kline（成交额/换手/close/high）
- gene_scores.db: zt_count_250d 股性活跃度 + code_industry 行业
- zt_history.db: 涨停+连板+fbt 首封时间
- dragon_tiger_history.db: 8 年席位 2123 天（inst_dominant walk-forward OOS edge-confirmed）
"""

from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import sys

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
GENE_DB = DATA / "gene_scores.db"
ZT_DB = DATA / "zt_history.db"
DT_DB = DATA / "dragon_tiger_history.db"

# 第一层财务硬过滤阈值（用户给 + 项目 sound）
MIN_AVG_AMT = 1.5e8  # 5 日均成交下限 1.5 亿
MIN_MV = 30e8  # 流通市值下限 30 亿（待 hithink 接入）
MAX_MV = 150e8  # 流通市值上限 150 亿（待 hithink 接入）
MAX_DEBT_RATIO = 85  # 资产负债率上限 85%（待 hithink 财报接入）

# 第二层情绪因子阈值（标 falsified，不假装 alpha）
TACTIC2_THRESHOLDS = {  # 战法2 尾盘趋势锁定（14:50）
    "换手率_min": 0.12,
    "换手率_max": 0.22,
    "收盘位置_min": 0.995,  # >=99.5% 日内最高
    "板块涨停数_min": 2,
    "龙虎榜席位占比": 0.08,
}

# verdict 诚实标注（R30，不藏 falsified）
VERDICTS: dict[str, str] = {
    "战法1_弱转强": "🔴 direction-confirmed falsified, magnitude-uncertain (-0.024%~-0.70%, 原-1.66%不可复现)",
    "战法2_尾盘锁定": "🔴 假edge falsified (survivorship+entry涨停价+exit一字 over-credit)",
    "红利低波_512890": "✅ 唯一诚实可落地 (7-11% beta)",
    "小市值动量": "⚠️ size exploratory BUT 不可做空+OOS fail",
    "inst_dominant_lhb": "✅ edge-confirmed walk-forward OOS (全量25327 mean+0.390% day_t=9.02 p=0.0000 跨regime稳健 2018-2024+0.354%/2025-2026+0.528%; walk-forward train+0.426%/test+0.345%都PASS衰减19%非过拟合; intraday -3% stop提高均值) BUT lottery(median负WR<50%)+R12预检不偏小盘(decile1-3占30%基线)完整BHAR待跑",
}

# chasing 维度（grilling 发现，排雷加分项）
CHASING_META = {
    "gap>=3%": "强烈回避 (-1.60% 反转)",
    "gap 1-3%": "回避 (-0.10%)",
    "gap<-1%": "无edge非输家 (+0.35% 但 lottery 结构 OOS 崩塌)",
}
INST_DOMINANT_META = "edge-confirmed walk-forward OOS (8年25327 mean+0.390% day_t=9.02 p=0.0000 跨regime稳健 2018-2024+0.354%/2025-2026+0.528%; train+0.426%/test+0.345%都PASS衰减19%非过拟合; intraday -3% stop) BUT lottery(median负WR<50%)+R12预检不偏小盘完整BHAR待跑"


@dataclass(frozen=True)
class FilterResult:
    """排雷结果（借鉴安全审查 JSON 模板）。"""

    code: str
    name: str
    is_passed: bool
    risk_level: str  # None/Low/High
    hit_rules: list  # 命中的雷/因子
    reason: str
    safe_action: str  # Pass(观察池)/Block(剔除)/Refuse(黑名单)
    verdicts: dict
    tactics_meta: dict


def _normalize_code(code: str) -> str:
    """code 统一为 6 位纯数字。

    baostock kline cache + gene_scores 都用 6 位纯数字（603778），
    用户可传 sh.603778 / sz.000001 / 603778，内部统一去前缀。
    """
    return code.replace("sh.", "").replace("sz.", "").replace("bj.", "")


def _load_kline(code: str) -> list[dict]:
    """从 baostock kline cache 取个股 bars（复用现有，不重造）。"""
    code6 = _normalize_code(code)
    conn = sqlite3.connect(str(KLINE_DB))
    row = conn.execute("SELECT bars_json FROM kline WHERE code=?", (code6,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        return json.loads(row[0])
    except Exception:
        return []


def _load_gene(code: str) -> dict:
    """从 gene_scores 取股性活跃度+行业（复用现有）。"""
    code6 = _normalize_code(code)
    conn = sqlite3.connect(str(GENE_DB))
    row = conn.execute(
        "SELECT name, zt_count_250d, industry FROM gene_scores WHERE code=? ORDER BY date DESC LIMIT 1", (code6,)
    ).fetchone()
    conn.close()
    if not row:
        return {}
    return {"name": row[0] or "", "zt_count_250d": row[1] or 0, "industry": row[2] or ""}


def _check_institutional_seat(code: str) -> dict:
    """R34 龙虎榜机构+外资席位识别（dragon_tiger_history 已有 1 年数据）。

    2026 短线主导是机构+外资（国泰海通总部/中信上海分公司/高盛世纪大道/
    瑞银花园石桥路/股通）非纯游资。识别机构+外资席位占比。
    返回 {has_lhb, inst_seats, inst_net_pct, is_inst_dominant}。

    标 edge-confirmed walk-forward OOS（8年25327 mean+0.390% day_t=9.02 p=0.0000 跨regime稳健;
    train+0.426%/test+0.345%都PASS衰减19%非过拟合; intraday -3% stop）。
    完整 R12 size-matched BHAR 待跑（预检不偏小盘 decile1-3 占30%基线）。
    """
    code6 = _normalize_code(code)
    conn = sqlite3.connect(str(DT_DB))
    rows = conn.execute(
        "SELECT dept_name, buy FROM dragon_tiger_rows WHERE security_code=? AND side='buy' "
        "AND trade_date=(SELECT MAX(trade_date) FROM dragon_tiger_rows WHERE security_code=?)",
        (code6, code6),
    ).fetchall()
    conn.close()
    if not rows:
        return {"has_lhb": False, "inst_seats": [], "inst_net_pct": 0.0, "is_inst_dominant": False}
    inst_keywords = (
        "机构专用",
        "总部",
        "高盛",
        "瑞银",
        "股通",
        "摩根",
        "中信证券股份有限公司上海分公司",
        "国际金融",
    )
    inst_seats = [r for r in rows if any(k in (r[0] or "") for k in inst_keywords)]
    total_buy = sum((r[1] or 0) for r in rows)
    inst_buy = sum((r[1] or 0) for r in inst_seats)
    inst_net_pct = inst_buy / total_buy if total_buy > 0 else 0.0
    return {
        "has_lhb": True,
        "inst_seats": [r[0] for r in inst_seats],
        "inst_net_pct": round(inst_net_pct, 3),
        "is_inst_dominant": inst_net_pct > 0.5,
    }


def _is_st(code: str, name: str = "") -> bool:
    """ST 判定（项目 astock isST 的简化，code 前缀 + 名称）。"""
    # 实际项目用 astock.is_st(code)，此处简化避免 import 重依赖
    return bool(name and ("ST" in name or "*ST" in name or "退" in name))


def first_layer_filter(code: str, name: str, bars: list[dict]) -> tuple[bool, list[str]]:
    """第一层财务硬过滤（一票否决，sound）。

    返回 (通过, 命中雷列表)。
    市值+资产负债率待 hithink 接入（T1.8/T1.9 TODO），暂用成交额+ST 降级。
    """
    hits: list[str] = []
    if _is_st(code, name):
        hits.append("ST/*ST/退市股")

    if len(bars) < 6:
        hits.append("数据不足无法算 5 日均成交")
        return len(hits) == 0, hits

    last5 = bars[-6:]
    # 5 日均成交额（baostock bar 有 amount）
    avg_amt = sum((b.get("amount", 0) or 0) for b in last5[:5]) / 5
    if avg_amt < MIN_AVG_AMT:
        hits.append(f"5 日均成交 {avg_amt / 1e8:.2f}亿 < 1.5 亿")

    # TODO T1.8: 流通市值从 hithink 取（30-150 亿）
    # TODO T1.9: 资产负债率从 hithink 财报取（>85% 剔除）

    return len(hits) == 0, hits


def second_layer_match(
    code: str, tactic: str, bars: list[dict], zt: dict | None, gene: dict
) -> tuple[bool, list[str], dict]:
    """第二层情绪因子匹配（标 falsified verdict，不假装 alpha）。

    返回 (匹配, 命中因子, meta)。
    """
    matched: list[str] = []
    meta: dict = {}

    if tactic == "战法1_弱转强":
        # 战法1 早盘弱转强（9:25）：竞价量比>3.5 / 竞价成交额占比>8% / 高开 2-5%
        # 项目无实时竞价数据，用 zt_history fbt（首封时间）代理竞价强度
        # 标 falsified verdict（R30）
        meta["verdict"] = VERDICTS["战法1_弱转强"]
        meta["chasing_gap"] = CHASING_META
        meta["inst_dominant"] = INST_DOMINANT_META
        if zt:
            fbt = zt.get("fbt")
            lbc = zt.get("lbc") or 1
            if fbt:
                matched.append(f"fbt 首封 {fbt}（代理竞价强度，待实时数据）")
            meta["lbc"] = lbc
            # lbc>=4 强烈回避（grilling：lbc=4 -2.18% 最差）
            if lbc >= 4:
                meta["lbc_warning"] = f"lbc={lbc} 强烈回避 (grilling: lbc=4 -2.18% 最差)"
        # 股性活跃度（gene_scores zt_count_250d）
        zt_count = gene.get("zt_count_250d", 0)
        meta["zt_count_250d"] = zt_count
        if zt_count >= 5:
            matched.append(f"股性活跃 zt_count_250d={zt_count}（过去 250 日涨停 {zt_count} 次）")

    elif tactic == "战法2_尾盘锁定":
        # 战法2 尾盘趋势锁定（14:50）：换手 12-22% / 收盘>=99.5% 日内最高 / 板块 2+涨停 / 龙虎榜>8%
        if len(bars) < 2:
            return False, matched, meta
        last = bars[-1]
        # 换手率（baostock bar 可能无 turn，降级跳过）
        turn = last.get("turn")
        if turn is not None and TACTIC2_THRESHOLDS["换手率_min"] <= turn <= TACTIC2_THRESHOLDS["换手率_max"]:
            matched.append(f"换手率 {turn:.2%} 在 12-22%")
        # 收盘位置（>=99.5% 日内最高）
        high = last.get("high", 0) or 0
        close = last.get("close", 0) or 0
        if high > 0 and close >= high * TACTIC2_THRESHOLDS["收盘位置_min"]:
            matched.append(f"收盘 {close} >=99.5% 日内最高 {high}")
        meta["verdict"] = VERDICTS["战法2_尾盘锁定"]
        # R34 龙虎榜机构+外资席位识别（dragon_tiger_history 已有 1 年数据）
        seat = _check_institutional_seat(code)
        meta["institutional_seat"] = seat
        if seat["has_lhb"] and seat["is_inst_dominant"]:
            matched.append(f"机构/外资席位主导 (inst_net_pct={seat['inst_net_pct']}, edge-confirmed walk-forward OOS)")
        elif seat["has_lhb"]:
            meta["seat_note"] = f"龙虎榜上榜但机构占比 {seat['inst_net_pct']}（非主导）"
        # TODO: 板块 2+涨停（需 code_industry + zt_history 当日同行业涨停数）

    elif tactic == "战法3_机构抱团":
        # 战法三 机构抱团龙虎榜低吸（用户给）：机构+外资席位>3 + 净买>8%
        # R34 机构化已实现（_check_institutional_seat）+ inst_dominant walk-forward OOS edge-confirmed
        # 战法三可量化部分=inst_dominant 已 edge-confirmed（memory inst-dominant-walkforward-oos-edge-confirmed）
        # "5日均线+底背离"主观技术指标矛盾（剔除，R27 买入可实现性 gate）
        seat = _check_institutional_seat(code)
        meta["institutional_seat"] = seat
        meta["verdict"] = VERDICTS["inst_dominant_lhb"]
        if seat["has_lhb"] and seat["is_inst_dominant"]:
            matched.append(f"机构/外资席位主导 (inst_net_pct={seat['inst_net_pct']}, edge-confirmed walk-forward OOS)")
        elif seat["has_lhb"]:
            meta["seat_note"] = f"龙虎榜上榜但机构占比 {seat['inst_net_pct']}（非主导，不达战法三门槛）"

    return len(matched) > 0, matched, meta


def filter_stock(code: str, tactic: str = "战法1_弱转强", zt: dict | None = None) -> FilterResult:
    """主排雷函数：第一层 → 第二层 → JSON 输出。

    不编主力意图（§1.2），只基于可观测量价/席位。
    """
    bars = _load_kline(code)
    gene = _load_gene(code)
    name = gene.get("name", code)

    # 第一层财务硬过滤（一票否决）
    pass1, hits1 = first_layer_filter(code, name, bars)
    if not pass1:
        return FilterResult(
            code=code,
            name=name,
            is_passed=False,
            risk_level="High",
            hit_rules=hits1,
            reason=f"第一层财务硬过滤未通过: {hits1}",
            safe_action="Block",
            verdicts=VERDICTS,
            tactics_meta={},
        )

    # 第二层情绪因子匹配（标 falsified）
    pass2, hits2, meta = second_layer_match(code, tactic, bars, zt, gene)

    risk = "Low" if pass2 else "High"
    action = "Pass" if pass2 else "Block"
    reason = (
        f"第一层财务过滤通过. "
        f"第二层{'匹配因子: ' + str(hits2) if hits2 else '未匹配因子'}. "
        f"verdict: {meta.get('verdict', '无')}"
    )

    return FilterResult(
        code=code,
        name=name,
        is_passed=pass2,
        risk_level=risk,
        hit_rules=hits2,
        reason=reason,
        safe_action=action,
        verdicts=VERDICTS,
        tactics_meta=meta,
    )


def to_json(r: FilterResult) -> dict:
    """输出 JSON（借鉴用户安全审查模板 is_passed/risk_level/hit_rules/reason/safe_action）。"""
    return {
        "code": r.code,
        "name": r.name,
        "is_passed": r.is_passed,
        "risk_level": r.risk_level,
        "hit_rules": r.hit_rules,
        "reason": r.reason,
        "safe_action": r.safe_action,
        "verdicts": r.verdicts,
        "tactics_meta": r.tactics_meta,
    }


if __name__ == "__main__":
    import sys

    code = sys.argv[1] if len(sys.argv) > 1 else "sh.600519"  # 默认贵州茅台测试
    tactic = sys.argv[2] if len(sys.argv) > 2 else "战法1_弱转强"
    r = filter_stock(code, tactic)
    print(json.dumps(to_json(r), ensure_ascii=False, indent=2))
