# -*- coding: utf-8 -*-
"""首板过滤 + 三层剔除 + 9 维度评分（tasks.md 003-021）。

实现范围：
- 003-006 数据层：fetch_zt_pool / filter_first_board / extract_chip_structure / extract_sector
- 007-010 剔除层：exclude_layer1_seal_quality / exclude_layer2_chip_structure /
                  exclude_layer3_market_env / run_first_board_filter 主入口
- 011-019 9 维度评分：score_dim1_sector ~ score_dim9_event
- 020 加权总分：score_candidate / rank_candidates
- 021 评分落盘：save_scores

阈值/权重集中在本模块顶部常量（EXCLUDE_THRESHOLDS / SCORE_WEIGHTS），**待回测校准**
（30 天后用实际数据调，见 tasks.md 021 回测校准）。

字段名说明（经核实，与东财 push2ex 实际返回一致，见
backend/risk/seal_intraday_collector.py:206-207 注释）：
- c→code, n→name, lbc→lbc(连板数,1=首板), zbc→break_times(炸板次数)
- fbt→first_seal(首封时间,数字 92500-145000,表示 09:25:00-14:50:00)
- fund→seal_amount(封单额,元)  ⚠️ 非 zje(zje 是涨停价)
- zje→limit_price(涨停价), p→price(现价)
- ltsz→float_cap(流通市值,元)  ⚠️ 非 float_shares*price(ltsz 直接可用)
- fundamt→amount(成交额,元), hybk→industry(行业)

合规：本模块按用户传入的 date 返回客观涨停池过滤结果，不预置标的、不排名、不建议。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from astock import em_zt_topic_pool, concept_blocks  # noqa: E402
from market import _emotion  # noqa: E402  私有函数，任务要求；后续可升级公开接口

_logger = logging.getLogger(__name__)

# 9 维度评分落盘目录（与 vr_paths 对齐，但本模块独立不依赖 vr_paths）
_SCORES_DIR = Path.home() / ".vibe-research"

# 沪深300 涨跌幅模块级缓存（date → pct%），避免 _market_drop_pct 重复 baostock login。
# baostock 查历史指数不入 kline_cache（缓存只含个股），故用 baostock 库实时查历史。
_HS300_PCT_CACHE: dict[str, float | None] = {}

# baostock_kline_cache 模块级缓存（code → bars list）。
# 31MB JSON 只读一次到内存，extract_chip_structure 复用，避免每只候选重读全文件（2s/只 → 0ms）。
_KLINE_CACHE: dict[str, list[dict]] | None = None

# ===========================================================================
# 阈值配置（待回测校准，30 天后用实际数据调）
# ===========================================================================
# 所有阈值集中在此常量，顶部统一管理。当前值为骨架占位，非回测校准值。
# 标注"待回测校准"：实际阈值需用 30 天首板数据回测后调整（见 tasks.md 021 回测校准）。
EXCLUDE_THRESHOLDS: dict = {
    # ── 层1 封板质量 ──────────────────────────────────────────────────────
    "max_break_times": 2,           # 炸板次数 ≥2 剔除（封板不牢）
    "late_seal_time": 140000,       # 首封时间 ≥14:00(数字140000) 剔除（尾盘偷袭）
    "min_seal_ratio": 0.005,        # 封单/流通市值 <0.5% 剔除（封单太薄）
    # ── 层2 筹码结构 ──────────────────────────────────────────────────────
    "max_turnover": 25.0,           # 换手率 >25% 剔除（筹码松动）
    "max_amount_yi": 15.0,          # 成交额 >15亿 剔除（资金分歧过大）
    "max_vol_ratio": 2.0,           # 量比 ≥2.0 剔除（放量过大，非自然涨停）
    # ── 层3 市场环境（T-1 粗筛）──────────────────────────────────────────
    "market_drop_threshold": -1.5,  # 大盘跌 >1.5% 标记高风险（不直接剔除，仅标记）
    "min_sector_zt_count": 2,       # 同板块涨停 <2 且无题材 剔除（孤板无板块效应）
}


# ===========================================================================
# 9 维度评分权重（待回测校准，30 天后用实际数据调）
# ===========================================================================
# 权重和为 1.0。当前值为 plan.md 权重，**待回测校准**（见 tasks.md 021 回测校准）。
# 每个维度函数顶部注释"§44 未 validated，待回测校准"——维度内部逻辑未经 §44 验证。
SCORE_WEIGHTS: dict = {
    "sector": 0.15,         # 维度1 板块评分（板块涨停≥3 只=联动强）
    "hot_money": 0.15,      # 维度2 游资画像（一日游占比高→扣分）
    "seal_strength": 0.20,  # 维度3 封板强度（封板越早/封单越大/不炸=越强）
    "chip": 0.10,           # 维度4 筹码结构（缩量+健康换手=筹码稳定）
    "auction": 0.10,        # 维度5 竞价确认（T 日 9:25 竞价高开 1-3%）
    "northbound": 0.10,     # 维度6 北向资金（正流入加分）
    "institution": 0.10,    # 维度7 龙虎榜机构（机构净买入=基本面认可）
    "theme": 0.05,          # 维度8 题材热度（同题材涨停≥3 只=满热度）
    "event": 0.05,          # 维度9 事件评分（#33/#34 利好+，#35-39 利空-）
}


# ===========================================================================
# 003-006 数据层
# ===========================================================================

def fetch_zt_pool(date: str) -> list[dict]:
    """取涨停池 raw dict list。

    Args:
        date: 交易日，格式 YYYYMMDD（如 "20260818"）。
              ⚠️ em_zt_topic_pool 用 YYYYMMDD；若传入 YYYY-MM-DD 会自动去横线。

    Returns:
        list[dict]：东财 push2ex getTopicZTPool 原始池，每项含
        c/n/lbc/zbc/fbt/fund/zje/p/ltsz/fundamt/hybk 等字段。
        非交易日或数据源故障 → []。
    """
    compact = date.replace("-", "") if "-" in date else date
    try:
        return em_zt_topic_pool("getTopicZTPool", compact, "fbt:asc") or []
    except Exception as e:
        _logger.warning("fetch_zt_pool 取涨停池失败 date=%s err=%s", date, e)
        return []


def _to_float(v) -> float | None:
    """raw 字段可能是 '-'(停牌)/None/str → 归一 float 或 None。"""
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


def _fbt_to_hhmm(fbt: float | None) -> str | None:
    """首封时间数字 → HH:MM 字符串。92500→"09:25"，145000→"14:50"。

    东财 fbt 格式：92500=09:25:00, 093000=09:30:00, 145000=14:50:00。
    用于剔除原因 reason 人话展示。
    """
    if fbt is None or fbt <= 0:
        return None
    try:
        n = int(fbt)
    except (TypeError, ValueError):
        return None
    if n < 0 or n > 235959:
        return None
    hh = n // 10000
    mm = (n // 100) % 100
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def filter_first_board(pool: list[dict]) -> list[dict]:
    """过滤首板（lbc=1）。

    东财口径：lbc=1 表示首板（今日首次涨停）。lbc 缺失或 0 也视为首板
    （历史数据兼容，东财偶尔返 0 表示首板）。

    Args:
        pool: em_zt_topic_pool("getTopicZTPool", ...) 原始池。

    Returns:
        list[dict]，每项字段：
        - code: str（c）
        - name: str（n）
        - price: float | None（p 或 zje，涨停价/现价）
        - lbc: int（连板数，首板=1）
        - break_times: float | None（zbc 炸板次数）
        - first_seal: float | None（fbt 首封时间，数字 92500-145000）
        - first_seal_hhmm: str | None（HH:MM 展示用）
        - seal_amount: float | None（fund 封单额，元）  ⚠️ 非 zje
        - float_cap: float | None（ltsz 流通市值，元）  ⚠️ 非 float_shares*price
        - amount: float | None（fundamt 成交额，元）
        - industry: str | None（hybk 行业）
    """
    out: list[dict] = []
    for p in pool or []:
        if not isinstance(p, dict):
            continue
        code = str(p.get("c", "") or "").strip()
        if not code:
            continue
        lbc_raw = _to_float(p.get("lbc"))
        # lbc=1 首板；lbc 缺失/0 也视为首板（东财偶尔返 0）
        lbc = int(lbc_raw) if lbc_raw is not None else 1
        if lbc_raw is not None and lbc > 1:
            continue  # 连板（2 板+），非首板，跳过

        price = _to_float(p.get("p")) or _to_float(p.get("zje"))
        fbt = _to_float(p.get("fbt"))
        out.append({
            "code": code,
            "name": p.get("n") or "",
            "price": price,
            "lbc": lbc,
            "break_times": _to_float(p.get("zbc")),
            "first_seal": fbt,
            "first_seal_hhmm": _fbt_to_hhmm(fbt),
            "seal_amount": _to_float(p.get("fund")),      # 封单额，元
            "float_cap": _to_float(p.get("ltsz")),        # 流通市值，元
            "amount": _to_float(p.get("fundamt")),         # 成交额，元
            "industry": p.get("hybk") or None,
        })
    return out


def extract_chip_structure(code: str, date: str | None = None) -> dict:
    """取 T-1 日筹码结构（换手率/量比/成交额）——历史数据，无未来函数。

    数据源：baostock_kline_cache.json 历史日K线（``turn``/``amount``/``volume``）。
    - turn：换手率%（baostock 字段，直接用）
    - amount：成交额元（baostock 字段，直接用）
    - vol_ratio：量比 = 当日每分钟均量 / 5 日每分钟均量
      （当日 volume/240 ÷ 前 5 日 volume 均值/240，240 = A 股开市分钟数）

    性能：31MB JSON 模块级缓存只读一次（``_KLINE_CACHE``），后续候选复用，
    避免每只重读全文件（旧实现 2s/只 → 0ms）。

    Args:
        code: 6 位股票代码。
        date: YYYY-MM-DD（T-1 日）。None → 返空 dict（无法定位历史 bar）。

    Returns:
        dict 含：
        - turnover_pct: float | None（换手率，百分数，如 8.5 表示 8.5%）
        - vol_ratio: float | None（量比）
        - amount: float | None（成交额，元）
        数据缺失/请求失败 → 空 dict {}（剔除层跳过该条件，不因数据缺失误剔除）。

    ⚠️ 无未来函数：全部用 date 当日及之前的历史 K 线，不用 tencent_quote 实时接口。
    旧实现调 tencent_quote([code]) 返回 T 日收盘筹码，用 T 日数据评判 T-1 首板 = 未来函数。
    """
    if not date:
        return {}
    # 归一 date 为 YYYY-MM-DD（baostock 缓存用此格式）
    d = date if "-" in date else f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    try:
        bars = _get_kline_cache().get(code, [])
        if not bars:
            return {}
        # 找 date 当日或之前最近的 bar（bars 已按日期升序，从末尾往前找）
        target_bar: dict | None = None
        target_idx = -1
        for i in range(len(bars) - 1, -1, -1):
            if bars[i].get("date", "") <= d:
                target_bar = bars[i]
                target_idx = i
                break
        if target_bar is None:
            return {}

        out: dict = {}
        tp = _to_float(target_bar.get("turn"))
        if tp is not None:
            out["turnover_pct"] = tp
        amt = _to_float(target_bar.get("amount"))
        if amt is not None:
            out["amount"] = amt

        # 量比 = 当日每分钟均量 / 5 日每分钟均量
        volume = _to_float(target_bar.get("volume")) or 0.0
        # 前 5 日（不含当日）：bars[target_idx-5 : target_idx]
        start = max(0, target_idx - 5)
        recent_5 = bars[start:target_idx]
        if recent_5:
            vols_5d = [_to_float(b.get("volume")) or 0.0 for b in recent_5]
            avg_5d = sum(vols_5d) / len(vols_5d)
            vol_ratio = (volume / 240.0) / (avg_5d / 240.0) if avg_5d > 0 else 1.0
            out["vol_ratio"] = round(vol_ratio, 2)
        # 数据不足（<5 日）→ 不设 vol_ratio，剔除/评分层降级跳过

        return out
    except Exception as e:
        _logger.warning("extract_chip_structure 历史数据失败 code=%s date=%s err=%s", code, d, e)
        return {}


def _get_kline_cache() -> dict[str, list[dict]]:
    """模块级懒加载 baostock_kline_cache.json（只读一次，后续复用）。

    31MB JSON 首次读约 2s，后续 0ms。run_first_board_filter 跑 52 只首板
    时只读一次，避免每只重读全文件（旧实现 52×2s=100s+ 卡死）。
    """
    global _KLINE_CACHE
    if _KLINE_CACHE is not None:
        return _KLINE_CACHE
    try:
        from vr_paths import resolve_data_dir
        cache_path = resolve_data_dir() / "baostock_kline_cache.json"
        if not cache_path.exists():
            _KLINE_CACHE = {}
            return _KLINE_CACHE
        cache = json.loads(cache_path.read_bytes())
    except Exception as e:
        _logger.warning("_get_kline_cache 读取失败 err=%s", e)
        cache = {}
    _KLINE_CACHE = cache
    return cache


def extract_sector(code: str) -> dict:
    """取个股板块/概念归属。

    Args:
        code: 6 位股票代码。

    Returns:
        dict 含：
        - boards: list[dict]（每项 {name, code, change_pct, lead_stock}）
        - concept_tags: list[str]（板块名列表）
        数据缺失/请求失败 → 空 dict {}。
    """
    try:
        raw = concept_blocks(code)
    except Exception as e:
        _logger.warning("extract_sector concept_blocks 失败 code=%s err=%s", code, e)
        return {}
    if not raw or not isinstance(raw, dict):
        return {}
    boards = raw.get("boards") or []
    tags = raw.get("concept_tags") or []
    if not boards and not tags:
        return {}
    return {"boards": boards, "concept_tags": tags}


# ===========================================================================
# 007-010 三层剔除
# ===========================================================================

def exclude_layer1_seal_quality(first_boards: list[dict]) -> tuple[list[dict], list[dict]]:
    """剔除层1：封板质量。

    条件（任一命中即剔除）：
    - 炸板次数 ≥ max_break_times（默认 2）
    - 首封时间 ≥ late_seal_time（默认 14:00，尾盘偷袭）
    - 封单/流通市值 < min_seal_ratio（默认 0.5%，封单太薄）

    数据缺失降级：break_times/first_seal/seal_amount/float_cap 任一缺失，
    跳过对应条件（不因数据缺失误剔除）。

    Args:
        first_boards: filter_first_board 返回的首板列表。

    Returns:
        (kept, filtered_records)：
        - kept: 通过层1的首板 list[dict]
        - filtered_records: 被剔除记录 list[dict]，每项 {code, layer:1, reason}
    """
    kept: list[dict] = []
    filtered: list[dict] = []

    max_bt = EXCLUDE_THRESHOLDS["max_break_times"]
    late_seal = EXCLUDE_THRESHOLDS["late_seal_time"]
    min_sr = EXCLUDE_THRESHOLDS["min_seal_ratio"]

    for fb in first_boards:
        code = fb.get("code", "")
        reasons: list[str] = []

        # 条件1：炸板次数
        bt = fb.get("break_times")
        if bt is not None and bt >= max_bt:
            reasons.append(f"炸板{int(bt)}次")

        # 条件2：首封时间（尾盘偷袭）
        fbt = fb.get("first_seal")
        if fbt is not None and fbt >= late_seal:
            hhmm = fb.get("first_seal_hhmm") or _fbt_to_hhmm(fbt) or ""
            reasons.append(f"首封{hhmm}尾盘")

        # 条件3：封单/流通市值
        seal = fb.get("seal_amount")
        fcap = fb.get("float_cap")
        if seal is not None and fcap is not None and fcap > 0:
            ratio = seal / fcap
            if ratio < min_sr:
                reasons.append(f"封单/流通市值{ratio*100:.2f}%")

        if reasons:
            filtered.append({
                "code": code,
                "layer": 1,
                "reason": "/".join(reasons),
            })
        else:
            kept.append(fb)

    return kept, filtered


def exclude_layer2_chip_structure(
    candidates: list[dict], date: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """剔除层2：筹码结构。

    条件（任一命中即剔除）：
    - 换手率 > max_turnover（默认 25%，筹码松动）
    - 成交额 > max_amount_yi 亿（默认 15 亿，资金分歧过大）
    - 量比 ≥ max_vol_ratio（默认 2.0，放量过大）

    数据来源：baostock_kline_cache.json 历史 K 线（换手/量比/成交额，无未来函数）。
    数据缺失降级：历史数据取不到 → 该字段 None → 跳过对应条件，
    **不因数据缺失误剔除**（宁可放过，不冤杀）。

    Args:
        candidates: 通过层1的候选 list[dict]。
        date: YYYY-MM-DD 或 YYYYMMDD（T-1 日，用于查 baostock 历史 K 线）。
              None → extract_chip_structure 返空，层2 全降级跳过（不误剔）。

    Returns:
        (kept, filtered_records)：同层1返回格式。
    """
    kept: list[dict] = []
    filtered: list[dict] = []

    max_to = EXCLUDE_THRESHOLDS["max_turnover"]
    max_amt_yi = EXCLUDE_THRESHOLDS["max_amount_yi"]
    max_vr = EXCLUDE_THRESHOLDS["max_vol_ratio"]

    for fb in candidates:
        code = fb.get("code", "")
        # 取筹码结构（若已缓存则复用；否则现取——用历史 K 线，无未来函数）
        chip = fb.get("_chip_structure")
        if chip is None:
            chip = extract_chip_structure(code, date)
            fb["_chip_structure"] = chip  # 缓存到候选对象，避免重复请求

        reasons: list[str] = []

        # 条件1：换手率
        tp = chip.get("turnover_pct")
        if tp is not None and tp > max_to:
            reasons.append(f"换手{tp:.0f}%筹码松动")

        # 条件2：成交额（优先用 tencent 的 amount，降级用涨停池的 amount）
        amt = chip.get("amount")
        if amt is None:
            amt = fb.get("amount")
        if amt is not None:
            amt_yi = amt / 1e8  # 元 → 亿
            if amt_yi > max_amt_yi:
                reasons.append(f"成交额{amt_yi:.1f}亿过大")

        # 条件3：量比
        vr = chip.get("vol_ratio")
        if vr is not None and vr >= max_vr:
            reasons.append(f"量比{vr:.1f}放量")

        if reasons:
            filtered.append({
                "code": code,
                "layer": 2,
                "reason": "/".join(reasons),
            })
        else:
            kept.append(fb)

    return kept, filtered


def _sector_zt_count(first_boards: list[dict], industry: str | None) -> int:
    """同板块涨停数（含首板+连板，基于 first_boards 池聚合）。

    industry 为 None 或空 → 返回 0（无法判定板块，视为孤板）。
    """
    if not industry:
        return 0
    return sum(1 for fb in first_boards if (fb.get("industry") or "") == industry)


def _market_drop_pct(date: str) -> float | None:
    """沪深300 当日涨跌幅（历史，无未来函数）。

    数据源：baostock 查 sh.000300 历史日K（``pctChg`` 字段=涨跌幅%）。
    baostock 指数 K 线不入 baostock_kline_cache.json（缓存只含个股），
    故用 baostock 库实时查历史指数（非实时行情，历史数据无未来函数）。
    模块级缓存避免重复 login。

    Args:
        date: YYYY-MMDD 或 YYYY-MM-DD（归一为 YYYY-MM-DD 查 baostock）。

    Returns:
        沪深300 涨跌幅（百分数，如 -1.8 表示跌 1.8%）。
        取不到 → None（不阻塞层3）。

    ⚠️ 无未来函数：用 date 当日历史指数数据，不用 index_quote() 实时接口。
    旧实现调 index_quote() 返回 T 日指数，用于 T-1 市场环境 = 未来函数。
    """
    d = date if "-" in date else f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    # 模块级缓存（date → pct），避免重复 login/query
    if d in _HS300_PCT_CACHE:
        return _HS300_PCT_CACHE[d]
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            _logger.warning("_market_drop_pct baostock login 失败 %s", lg.error_msg)
            return None
        rs = bs.query_history_k_data_plus(
            "sh.000300", "date,pctChg",
            start_date=d, end_date=d,
        )
        if rs.error_code != "0":
            _logger.warning("_market_drop_pct baostock 查询失败 %s", rs.error_msg)
            return None
        pct: float | None = None
        while rs.next():
            row = rs.get_row_data()
            if row and row[1]:
                pct = _to_float(row[1])
                break
        _HS300_PCT_CACHE[d] = pct
        return pct
    except Exception as e:
        _logger.warning("_market_drop_pct baostock 指数失败 date=%s err=%s", d, e)
        return None


def exclude_layer3_market_env(
    candidates: list[dict], date: str, first_boards: list[dict] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """剔除层3：市场环境（T-1 粗筛）。

    条件：
    - 大盘跌 > market_drop_threshold（默认 -1.5%）→ 标记 high_risk（不直接剔除，
      仅在 env_flags 标记；实盘需结合其他信号）
    - 同板块涨停 < min_sector_zt_count（默认 2）且无题材 → 剔除（孤板无板块效应）

    数据来源：market._emotion(date)（max_boards/ladder）+ 上证指数实时行情 +
    first_boards 自身同板块聚合。

    数据缺失降级：_emotion 返空或指数取不到 → env_flags 对应字段 None，
    不剔除（层3 失败不阻塞候选）。

    Args:
        candidates: 通过层2的候选 list[dict]。
        date: YYYYMMDD 或 YYYY-MM-DD，涨停池日期。
        first_boards: filter_first_board 返回的首板池（用于同板块聚合）。
                      None 则用 candidates 自身（候选池可能已过滤，板块计数偏小）。

    Returns:
        (kept, filtered_records, env_flags)：
        - kept: 通过层3的候选 list[dict]
        - filtered_records: 被剔除记录 list[dict]，每项 {code, layer:3, reason}
        - env_flags: dict 含
            - market_drop_pct: float | None（上证涨跌幅，百分数）
            - high_risk: bool（大盘跌 >1.5% 标记）
            - max_boards: int | None（最高连板）
            - ladder_broken: bool（无连板梯队，max_boards<2）
    """
    fb_pool = first_boards if first_boards is not None else candidates

    # 取市场情绪（max_boards/ladder）
    emotion: dict = {}
    try:
        emotion = _emotion(date) or {}
    except Exception as e:
        _logger.warning("exclude_layer3 _emotion 失败 date=%s err=%s", date, e)
        emotion = {}

    max_boards_raw = emotion.get("max_boards")
    max_boards = int(max_boards_raw) if max_boards_raw is not None else None
    ladder = emotion.get("ladder") or []
    ladder_broken = (max_boards is not None and max_boards < 2) or (not ladder)

    # 取大盘涨跌幅
    market_drop = _market_drop_pct(date)
    threshold = EXCLUDE_THRESHOLDS["market_drop_threshold"]
    high_risk = (market_drop is not None and market_drop <= threshold)

    env_flags: dict = {
        "market_drop_pct": market_drop,
        "high_risk": high_risk,
        "max_boards": max_boards,
        "ladder_broken": ladder_broken,
    }

    # 层3 剔除：同板块涨停 <2 且无题材（孤板无板块效应）
    min_sector_count = EXCLUDE_THRESHOLDS["min_sector_zt_count"]

    kept: list[dict] = []
    filtered: list[dict] = []

    for fb in candidates:
        code = fb.get("code", "")
        industry = fb.get("industry")

        # 同板块涨停数（基于 first_boards 池聚合，含首板+连板）
        sector_count = _sector_zt_count(fb_pool, industry)

        # 取概念题材（若已缓存则复用）
        sector_info = fb.get("_sector_info")
        if sector_info is None:
            sector_info = extract_sector(code)
            fb["_sector_info"] = sector_info
        concept_tags = sector_info.get("concept_tags") or []

        reasons: list[str] = []

        # 同板块涨停 < min_sector_zt_count 且无题材 → 剔除
        if sector_count < min_sector_count and not concept_tags:
            reasons.append(
                f"同板块{sector_count}家涨停无题材"
            )

        # 注意：high_risk / ladder_broken 不直接剔除，仅在 env_flags 标记
        # （T-1 粗筛语义：高风险市场环境下降低仓位，不直接清空候选）

        if reasons:
            filtered.append({
                "code": code,
                "layer": 3,
                "reason": "/".join(reasons),
            })
        else:
            kept.append(fb)

    return kept, filtered, env_flags


# ===========================================================================
# 011-019 9 维度评分（每维度 0-100，数据缺失降级 50 中性）
# ===========================================================================
# 统一签名：def score_dimN_code(candidate: dict, date: str) -> float
# 返回 0-100 分。数据缺失时 try/except 返 50 分中性（不抛异常，不阻塞主流程）。
# 每个维度顶部注释"§44 未 validated，待回测校准"——维度内部逻辑未经 §44 验证。

# ── 维度1：板块评分（权重 15%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：sector_cycle.aggregate_sectors / sector_strength_rank + 连板梯队
# 逻辑：板块涨停≥3 只=联动强，0-100 归一化。板块强度排名 TOP3 → 高分。

def score_dim1_sector(candidate: dict, date: str) -> tuple[float, dict]:
    """板块评分。

    逻辑：
    - 调 sector_cycle.aggregate_sectors(date) 取当日板块强度排名
    - 候选股 industry 命中 TOP3 板块 → 90-100 分
    - TOP4-10 → 70-89 分
    - 其他有板块 → 50-69 分
    - 无板块/数据缺失 → 50 分中性

    Args:
        candidate: filter_first_board 产出的候选 dict（含 industry 字段）。
        date: YYYYMMDD。

    Returns:
        (score, raw)：raw 含 sector_rank（板块排名）/sector_zt_count（板块涨停数）。
        数据缺失时 raw 对应字段 None。
    """
    raw: dict = {"sector_rank": None, "sector_zt_count": None}
    try:
        from strategies.sector_cycle import aggregate_sectors, sector_strength_rank
        sectors = aggregate_sectors(date)
        if not sectors:
            return 50.0, raw
        ranked = sector_strength_rank(date, sectors)
        industry = candidate.get("industry") or ""
        if not industry:
            return 50.0, raw
        for s in ranked:
            if (s.get("industry") or "") == industry:
                rank = s.get("rank", 999)
                zt_count = s.get("zt_count_today", 0)
                raw["sector_rank"] = rank
                raw["sector_zt_count"] = zt_count
                # 排名越前 + 板块涨停数越多 → 分越高
                if rank <= 3:
                    base = 90.0
                elif rank <= 10:
                    base = 70.0
                else:
                    base = 50.0
                # 板块涨停≥3 只加 5 分（联动强）
                if zt_count >= 3:
                    base = min(base + 5.0, 100.0)
                return round(base, 1), raw
        # industry 不在排名中（可能候选 industry 字段与板块名不一致）
        return 50.0, raw
    except Exception as e:
        _logger.debug("score_dim1_sector 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度2：游资画像（权重 15%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：hot_money_seats.compute_seat_risk_factor
# 逻辑：一日游占比高→×0.7 扣分，接力型→加分，0-100 归一化。

def score_dim2_hot_money(candidate: dict, date: str) -> tuple[float, dict]:
    """游资画像评分。

    逻辑：
    - 调 compute_seat_risk_factor(code, date) 取 SeatRiskFactor
    - score_modifier 1.0 → 70 分基准（中性游资参与）
    - score_modifier 0.7（高风险一日游）→ 70 × 0.7 = 49 分
    - score_modifier 0.9（中风险）→ 63 分
    - score_modifier 1.05（接力支撑）→ 73.5 分
    - 无龙虎榜数据（risk_label="无数据"）→ 50 分中性

    Args:
        candidate: 候选 dict（含 code）。
        date: YYYYMMDD（compute_seat_risk_factor 用 YYYY-MM-DD，内部转换）。

    Returns:
        (score, raw)：raw 含 seat_risk_label（风险标签）/one_day_ratio（一日游占比）。
        数据缺失时 raw 对应字段 None。
    """
    raw: dict = {"seat_risk_label": None, "one_day_ratio": None}
    try:
        from strategies.hot_money_seats import compute_seat_risk_factor
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        # date 转 YYYY-MM-DD（compute_seat_risk_factor 接受此格式）
        d = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
        factor = compute_seat_risk_factor(code, d)
        raw["seat_risk_label"] = factor.risk_label
        raw["one_day_ratio"] = factor.day_trip_ratio
        if factor.risk_label == "无数据":
            return 50.0, raw
        # score_modifier 0.7-1.05 → 0-100 分（1.0=70 基准）
        score = 70.0 * factor.score_modifier
        return round(max(0.0, min(100.0, score)), 1), raw
    except Exception as e:
        _logger.debug("score_dim2_hot_money 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度3：封板强度（权重 20%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：ZTPoolItem 封单/首封/炸板 + breakout_20d（可选）+ 振幅
# 逻辑：封板越早/封单越大/不炸=越强，0-100 加权。

def score_dim3_seal_strength(candidate: dict, date: str) -> tuple[float, dict]:
    """封板强度评分。

    逻辑（加权，各子项 0-100）：
    - 首封时间（40%）：9:25-9:30 满分，越晚越低，14:00 后 0 分
    - 封单/流通市值（30%）：≥2% 满分，<0.5% 0 分
    - 炸板次数（30%）：0 炸板满分，≥2 次 0 分

    Args:
        candidate: 候选 dict（含 first_seal/seal_amount/float_cap/break_times）。
        date: YYYYMMDD（本维度不直接用，预留）。

    Returns:
        (score, raw)：raw 含 first_seal/seal_amount/float_cap/seal_ratio/break_times。
        数据缺失时对应字段 None。
    """
    raw: dict = {
        "first_seal": None, "seal_amount": None, "float_cap": None,
        "seal_ratio": None, "break_times": None,
    }
    try:
        # 子项1：首封时间（92500-145000 → 0-100）
        fbt = candidate.get("first_seal")
        raw["first_seal"] = fbt
        time_score = 50.0  # 缺失中性
        if fbt is not None and 90000 <= fbt <= 150000:
            # 92500=满分，145000=0 分，线性递减
            if fbt <= 93000:
                time_score = 100.0  # 开盘秒板
            elif fbt <= 100000:
                time_score = 90.0  # 早盘
            elif fbt <= 130000:
                time_score = 70.0  # 上午-午后
            elif fbt <= 140000:
                time_score = 40.0  # 下午
            else:
                time_score = 20.0  # 尾盘

        # 子项2：封单/流通市值
        seal = candidate.get("seal_amount")
        fcap = candidate.get("float_cap")
        raw["seal_amount"] = seal
        raw["float_cap"] = fcap
        seal_score = 50.0  # 缺失中性
        if seal is not None and fcap is not None and fcap > 0:
            ratio = seal / fcap  # 0-1
            raw["seal_ratio"] = round(ratio, 4)
            if ratio >= 0.02:
                seal_score = 100.0
            elif ratio >= 0.01:
                seal_score = 80.0
            elif ratio >= 0.005:
                seal_score = 60.0
            elif ratio >= 0.001:
                seal_score = 30.0
            else:
                seal_score = 10.0

        # 子项3：炸板次数
        bt = candidate.get("break_times")
        raw["break_times"] = bt
        bt_score = 100.0  # 缺失视为不炸（满分）
        if bt is not None:
            if bt == 0:
                bt_score = 100.0
            elif bt == 1:
                bt_score = 60.0
            elif bt >= 2:
                bt_score = 0.0

        total = time_score * 0.40 + seal_score * 0.30 + bt_score * 0.30
        return round(max(0.0, min(100.0, total)), 1), raw
    except Exception as e:
        _logger.debug("score_dim3_seal_strength 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度4：筹码结构（权重 10%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：tencent_quote 换手/量比/成交额/振幅
# 逻辑：缩量+健康换手=筹码稳定，0-100 加权。

def score_dim4_chip(candidate: dict, date: str) -> tuple[float, dict]:
    """筹码结构评分。

    逻辑（加权，各子项 0-100）：
    - 换手率（40%）：5-15% 健康满分，>25% 筹码松动 0 分，<2% 过冷 30 分
    - 量比（30%）：0.8-1.5 健康满分，≥2.0 放量 0 分
    - 成交额（30%）：1-10 亿健康满分，>15 亿过大 0 分

    数据来源：tencent_quote（实时/盘后收盘行情）。
    数据缺失 → 该子项 50 分中性，不因缺失误判。

    Returns:
        (score, raw)：raw 含 turnover（换手率%）/vol_ratio（量比）/amount（成交额元）。
        数据缺失时对应字段 None。
    """
    raw: dict = {"turnover": None, "vol_ratio": None, "amount": None}
    try:
        chip = candidate.get("_chip_structure")
        if chip is None:
            chip = extract_chip_structure(candidate.get("code", ""), date)
            candidate["_chip_structure"] = chip

        # 子项1：换手率
        tp = chip.get("turnover_pct")
        raw["turnover"] = tp
        tp_score = 50.0
        if tp is not None:
            if 5.0 <= tp <= 15.0:
                tp_score = 100.0
            elif 2.0 <= tp < 5.0 or 15.0 < tp <= 25.0:
                tp_score = 70.0
            elif tp > 25.0:
                tp_score = 0.0
            else:  # < 2.0
                tp_score = 30.0

        # 子项2：量比
        vr = chip.get("vol_ratio")
        raw["vol_ratio"] = vr
        vr_score = 50.0
        if vr is not None:
            if 0.8 <= vr <= 1.5:
                vr_score = 100.0
            elif 0.5 <= vr < 0.8 or 1.5 < vr < 2.0:
                vr_score = 70.0
            elif vr >= 2.0:
                vr_score = 0.0
            else:  # < 0.5
                vr_score = 30.0

        # 子项3：成交额（优先 tencent amount，降级涨停池 amount）
        amt = chip.get("amount")
        if amt is None:
            amt = candidate.get("amount")
        raw["amount"] = amt
        amt_score = 50.0
        if amt is not None:
            amt_yi = amt / 1e8  # 元 → 亿
            if 1.0 <= amt_yi <= 10.0:
                amt_score = 100.0
            elif 0.3 <= amt_yi < 1.0 or 10.0 < amt_yi <= 15.0:
                amt_score = 70.0
            elif amt_yi > 15.0:
                amt_score = 0.0
            else:  # < 0.3 亿
                amt_score = 30.0

        total = tp_score * 0.40 + vr_score * 0.30 + amt_score * 0.30
        return round(max(0.0, min(100.0, total)), 1), raw
    except Exception as e:
        _logger.debug("score_dim4_chip 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度5：竞价确认（权重 10%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：T 日 9:25 竞价高开 1-3% + 竞价量≥昨日 5%
# 逻辑：T 日盘前实时，T-1 盘后预填 0 待 T 日更新。

def score_dim5_auction(candidate: dict, date: str) -> tuple[float, dict]:
    """竞价确认评分。

    T-1 盘后跑时预填 0（无 T 日竞价数据），T 日盘前更新。
    本维度需要 T 日 9:25 竞价数据，T-1 盘后不可得 → 返 0 分（标注待 T 日更新）。

    Returns:
        (score, raw)：raw 含 auction_open_pct/auction_vol_ratio。
        T-1 盘后无 T 日竞价数据 → raw 两字段均 None，score=0。
    """
    # T-1 盘后无 T 日竞价数据 → 预填 0，待 T 日盘前更新
    # 实盘接入时从 astock 取 T 日 9:25 竞价数据后重算
    raw: dict = {"auction_open_pct": None, "auction_vol_ratio": None}
    return 0.0, raw


# ── 维度6：北向资金（权重 10%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：predict.features.fund_flow.fetch_northbound 个股北向净流入
# 逻辑：正流入加分（2024-08-19 后停更降级 50 分）

def score_dim6_northbound(candidate: dict, date: str) -> tuple[float, dict]:
    """北向资金评分。

    逻辑：
    - 调 fetch_northbound(code, date) 取个股北向净流入（万元）
    - 正流入（>0）→ 70-100 分（越大越高）
    - 负流出（<0）→ 0-50 分
    - None（停更/无数据）→ 50 分中性

    2024-08-19 北向规则变更后个股日级北向数据停更，返 None → 50 分中性。

    Returns:
        (score, raw)：raw 含 northbound_net（北向净流入，万元）。
        停更/无数据 → None。
    """
    raw: dict = {"northbound_net": None}
    try:
        from predict.features.fund_flow import fetch_northbound
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        d = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
        nb = fetch_northbound(code, d)  # 万元
        raw["northbound_net"] = nb
        if nb is None:
            # 2024-08-19 后个股北向停更 / 当日无数据 → 50 分中性
            return 50.0, raw
        if nb > 0:
            # 正流入：0-10000 万 → 70-100 分（对数缩放，避免极值）
            import math
            score = 70.0 + min(30.0, math.log10(max(nb, 1.0)) * 10.0)
            return round(max(0.0, min(100.0, score)), 1), raw
        else:
            # 负流出：0 到 -5000 万 → 50 到 0 分
            score = max(0.0, 50.0 + (nb / 100.0))  # 每流出 100 万扣 1 分
            return round(max(0.0, min(100.0, score)), 1), raw
    except Exception as e:
        _logger.debug("score_dim6_northbound 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度7：龙虎榜机构（权重 10%）──────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：astock.dragon_tiger_board + data.mappers.dragon_tiger_from_dict
# 逻辑：机构净买入=基本面认可（无龙虎榜降级 50 分）

def score_dim7_institution(candidate: dict, date: str) -> tuple[float, dict]:
    """龙虎榜机构评分。

    逻辑：
    - 调 astock.dragon_tiger_board(code) 取机构净买入（万元）
    - 机构净买入 >0 → 70-100 分（越大越高）
    - 机构净卖出 <0 → 0-50 分
    - 无龙虎榜 / 无机构席位 → 50 分中性

    Returns:
        (score, raw)：raw 含 inst_net（机构净买入，万元）。
        无龙虎榜/无机构席位 → None。
    """
    raw: dict = {"inst_net": None}
    try:
        from astock import dragon_tiger_board
        from data.mappers import dragon_tiger_from_dict
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        raw_dt = dragon_tiger_board(code) or {}
        dt = dragon_tiger_from_dict(raw_dt)
        inst_net = dt.institution_net  # 万元
        raw["inst_net"] = inst_net
        if inst_net is None:
            # 无龙虎榜 / 无机构席位 → 50 分中性
            return 50.0, raw
        if inst_net > 0:
            # 机构净买入：0-5000 万 → 70-100 分
            import math
            score = 70.0 + min(30.0, math.log10(max(inst_net, 1.0)) * 10.0)
            return round(max(0.0, min(100.0, score)), 1), raw
        else:
            # 机构净卖出：每卖出 100 万扣 1 分
            score = max(0.0, 50.0 + (inst_net / 100.0))
            return round(max(0.0, min(100.0, score)), 1), raw
    except Exception as e:
        _logger.debug("score_dim7_institution 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度8：题材热度（权重 5%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：astock.ths_limit_up_pool reason 聚合
# 逻辑：同题材涨停≥3 只=满热度

def score_dim8_theme(candidate: dict, date: str) -> tuple[float, dict]:
    """题材热度评分。

    逻辑：
    - 调 ths_limit_up_pool(date) 取涨停池 reason 题材聚合
    - 候选股 reason 命中题材涨停≥3 只 → 100 分（满热度）
    - 2 只 → 70 分
    - 1 只（自身）→ 30 分（无题材热度）
    - 无 reason / 数据缺失 → 50 分中性

    Returns:
        (score, raw)：raw 含 theme_zt_count（同题材涨停数）/theme_name（命中的题材名）。
        数据缺失时对应字段 None。
    """
    raw: dict = {"theme_zt_count": None, "theme_name": None}
    try:
        from astock import ths_limit_up_pool
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        pool = ths_limit_up_pool(date)
        if not pool:
            return 50.0, raw
        # 找到候选股的 reason
        cand_item = next((p for p in pool if p.get("code") == code), None)
        if not cand_item or not cand_item.get("reason"):
            return 50.0, raw
        reason = cand_item["reason"]
        raw["theme_name"] = reason
        # split 题材（+ / 、 / ; 等分隔）
        for sep in ("+", "、", ";", "，", "/"):
            reason = reason.replace(sep, "+")
        tags = [t.strip() for t in reason.split("+") if t.strip()]
        if not tags:
            return 50.0, raw
        # 聚合每个题材的涨停数
        concept_count: dict[str, int] = {}
        for item in pool:
            r = (item.get("reason") or "").strip()
            if not r:
                continue
            for sep in ("+", "、", ";", "，", "/"):
                r = r.replace(sep, "+")
            for tag in r.split("+"):
                tag = tag.strip()
                if tag:
                    concept_count[tag] = concept_count.get(tag, 0) + 1
        # 取候选股题材的最大涨停数
        max_count = max((concept_count.get(t, 0) for t in tags), default=0)
        raw["theme_zt_count"] = max_count
        # theme_name 精确为涨停数最多的那个题材
        if tags:
            best_tag = max(tags, key=lambda t: concept_count.get(t, 0))
            raw["theme_name"] = best_tag
        if max_count >= 3:
            return 100.0, raw
        elif max_count == 2:
            return 70.0, raw
        elif max_count == 1:
            return 30.0, raw
        else:
            return 50.0, raw
    except Exception as e:
        _logger.debug("score_dim8_theme 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度9：事件评分（权重 5%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：astock.announcements + news_radar_context.classify_announcement
# 逻辑：#33/#34 利多加分 + #35-39 利空扣分，无公告=50 分中性

def score_dim9_event(candidate: dict, date: str) -> tuple[float, dict]:
    """事件评分。

    逻辑：
    - 调 astock.announcements(code) 取近期公告
    - 用 classify_announcement(title) 分类
    - 预增/扭亏/重组/回购/增持（#33/#34 利好）→ 70-100 分
    - 风险提示（#35-39 利空）→ 0-30 分
    - 未知/无公告 → 50 分中性

    Args:
        candidate: 候选 dict（含 code）。
        date: YYYYMMDD（本维度取近期公告，不严格按 date）。

    Returns:
        (score, raw)：raw 含 event_type（利多/利空/中性分类）/announcement_title（公告标题）。
        无公告时 event_type="无公告"，announcement_title=None。
    """
    raw: dict = {"event_type": None, "announcement_title": None}
    try:
        from astock import announcements
        from strategies.news_radar_context import classify_announcement
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        anns = announcements(code, limit=10) or []
        if not anns:
            # 无公告 → 50 分中性
            raw["event_type"] = "无公告"
            return 50.0, raw
        # 取最近一条公告分类
        latest = anns[0] if isinstance(anns[0], dict) else {}
        title = latest.get("title") or ""
        raw["announcement_title"] = title
        ann_type = classify_announcement(title)
        raw["event_type"] = ann_type
        if ann_type in ("预增", "扭亏", "重组", "回购", "增持"):
            # 利好：预增/扭亏=90，重组=85，回购=80，增持=75
            score_map = {"预增": 90.0, "扭亏": 90.0, "重组": 85.0, "回购": 80.0, "增持": 75.0}
            return score_map.get(ann_type, 70.0), raw
        elif ann_type == "风险提示":
            # 利空：0-30 分
            return 20.0, raw
        else:
            # 未知/其他 → 50 分中性
            return 50.0, raw
    except Exception as e:
        _logger.debug("score_dim9_event 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ===========================================================================
# 020 9 维度加权总分 + 排序
# ===========================================================================

# 维度函数映射表（score_candidate 用，避免 if-else 链）
_SCORE_DIMS = [
    ("sector", score_dim1_sector),
    ("hot_money", score_dim2_hot_money),
    ("seal_strength", score_dim3_seal_strength),
    ("chip", score_dim4_chip),
    ("auction", score_dim5_auction),
    ("northbound", score_dim6_northbound),
    ("institution", score_dim7_institution),
    ("theme", score_dim8_theme),
    ("event", score_dim9_event),
]


def score_candidate(candidate: dict, date: str) -> dict:
    """9 维度评分。

    Args:
        candidate: filter_first_board 产出的候选 dict（含 code/industry/seal_amount 等）。
        date: YYYYMMDD。

    Returns:
        dict 含：
        - code: str
        - name: str
        - scores: dict（{dim_name: score}，9 个维度）
        - raw_values: dict（{dim_name: raw_dict}，每维度的原始值，供"实际值→得分"对照）
        - total: float（0-100 加权总分）
        - rank: int（排名，score_candidate 不填，rank_candidates 填）

    ⚠️ 维度函数返回 (score, raw) 元组（新签名）；兼容旧签名（只返 float）用
    isinstance 判定，旧签名 raw=空 dict。
    """
    scores: dict = {}
    raw_values: dict = {}
    total = 0.0
    for dim_name, dim_fn in _SCORE_DIMS:
        weight = SCORE_WEIGHTS[dim_name]
        result = dim_fn(candidate, date)
        # 兼容旧签名（只返 float）和新签名（返 tuple）
        if isinstance(result, tuple):
            score, raw = result
        else:
            score, raw = float(result), {}
        # 钳制 0-100
        score = max(0.0, min(100.0, score))
        scores[dim_name] = score
        raw_values[dim_name] = raw
        total += score * weight

    return {
        "code": candidate.get("code", ""),
        "name": candidate.get("name", ""),
        "scores": scores,
        "raw_values": raw_values,
        "total": round(total, 1),
        "rank": 0,  # rank_candidates 填
    }


def rank_candidates(candidates: list[dict], date: str) -> list[dict]:
    """按总分降序排序。

    Args:
        candidates: 通过三层剔除的候选 list[dict]。
        date: YYYYMMDD。

    Returns:
        list[dict]（按 total 降序），每项含 scores+total+rank（1-based）。

    进度日志：每 5 只打一条进度（flush=True，后台跑实时输出）。
    兜底：单只 score_candidate 失败 try/except 跳过（不进 scored，不阻塞整批）。
    """
    scored: list[dict] = []
    n = len(candidates)
    for i, c in enumerate(candidates):
        if i % 5 == 0 or i == n - 1:
            print(f"[fb_filter] 评分进度: {i}/{n} code={c.get('code')}", flush=True)
        try:
            scored.append(score_candidate(c, date))
        except Exception as e:
            _logger.warning("score_candidate 失败 code=%s err=%s", c.get("code"), e)
    print(f"[fb_filter] 评分进度: {n}/{n} 完成", flush=True)
    scored.sort(key=lambda x: x["total"], reverse=True)
    for i, s in enumerate(scored):
        s["rank"] = i + 1
    return scored


# ===========================================================================
# 021 评分落盘
# ===========================================================================

def save_scores(scored: list[dict], date: str, full_result: dict | None = None) -> Path:
    """存 ~/.vibe-research/first_board_scores_{date}.json。

    Args:
        scored: rank_candidates 返回的评分列表。
        date: YYYYMMDD（用于文件名）。
        full_result: run_first_board_filter 的完整返回（含 zt_pool_count/excluded/env_flags），
            传入则一并落盘，供历史快照还原 Pipeline 全过程数据。

    Returns:
        Path：落盘文件路径。
    """
    _SCORES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _SCORES_DIR / f"first_board_scores_{date}.json"
    meta = {
        "date": date,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(scored),
        "weights": SCORE_WEIGHTS,
        "note": "9 维度评分，权重待回测校准（见 tasks.md 021）",
    }
    payload = {"_meta": meta, "scored_candidates": scored}
    if full_result is not None:
        payload["zt_pool_count"] = full_result.get("zt_pool_count", 0)
        payload["first_board_count"] = full_result.get("first_board_count", 0)
        payload["excluded"] = full_result.get("excluded", [])
        payload["env_flags"] = full_result.get("env_flags", {})
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_scores(date: str) -> dict | None:
    """读 ~/.vibe-research/first_board_scores_{date}.json 历史快照。

    Args:
        date: YYYYMMDD 或 YYYY-MM-DD（内部归一为 YYYYMMDD）。

    Returns:
        dict 含：
        - date: str（快照日期 YYYYMMDD）
        - scored_candidates: list[dict]（9 维度评分列表）
        - updated_at: str（落盘时间戳）
        - zt_pool_count: int（新版本落盘，旧快照缺=0）
        - first_board_count: int
        - excluded: list[dict]
        - env_flags: dict
        无快照/读取失败 → None。
    """
    compact = date.replace("-", "") if "-" in date else date
    path = _SCORES_DIR / f"first_board_scores_{compact}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _logger.warning("load_scores 读取失败 date=%s err=%s", compact, e)
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("_meta", {})
    return {
        "date": meta.get("date", compact),
        "scored_candidates": data.get("scored_candidates", []),
        "updated_at": meta.get("updated_at", ""),
        "zt_pool_count": data.get("zt_pool_count", 0),
        "first_board_count": data.get("first_board_count", 0),
        "excluded": data.get("excluded", []),
        "env_flags": data.get("env_flags", {}),
    }


def list_score_dates() -> list[str]:
    """列出所有有快照的日期（YYYYMMDD 格式，降序）。

    扫描 _SCORES_DIR 下的 first_board_scores_YYYYMMDD.json 文件，
    返回日期字符串列表（最近的在前）。目录不存在/无文件 → []。
    """
    if not _SCORES_DIR.exists():
        return []
    dates: list[str] = []
    for p in _SCORES_DIR.glob("first_board_scores_*.json"):
        # 文件名 first_board_scores_20260818.json → stem first_board_scores_20260818
        stem = p.stem.replace("first_board_scores_", "")
        if stem.isdigit() and len(stem) == 8:
            dates.append(stem)
    dates.sort(reverse=True)
    return dates


def run_first_board_filter(date: str) -> dict:
    """主入口：串联 003-010（数据层 + 三层剔除）。

    Args:
        date: 交易日，YYYYMMDD 或 YYYY-MM-DD。

    Returns:
        dict 含：
        - date: str（标准化为 YYYYMMDD）
        - zt_pool_count: int（涨停池总数）
        - first_board_count: int（首板数）
        - candidates: list[dict]（通过三层剔除的候选池）
        - excluded: list[dict]（全部剔除记录 [{code, layer, reason}]）
        - env_flags: dict（层3 市场环境标记）
    """
    # 日期标准化
    compact_date = date.replace("-", "") if "-" in date else date

    print(f"[fb_filter] 开始 date={compact_date}", flush=True)

    # 003 取涨停池
    pool = fetch_zt_pool(compact_date)
    zt_pool_count = len(pool)
    print(f"[fb_filter] 涨停池: {zt_pool_count}", flush=True)

    # 004 过滤首板
    first_boards = filter_first_board(pool)
    first_board_count = len(first_boards)
    print(f"[fb_filter] 首板: {first_board_count}", flush=True)

    excluded: list[dict] = []

    # 007 层1 封板质量
    after_l1, filtered_l1 = exclude_layer1_seal_quality(first_boards)
    excluded.extend(filtered_l1)
    print(f"[fb_filter] 层1剔除: {len(filtered_l1)} 剩余: {len(after_l1)}", flush=True)

    # 008 层2 筹码结构（传 date 取历史 K 线，无未来函数）
    after_l2, filtered_l2 = exclude_layer2_chip_structure(after_l1, compact_date)
    excluded.extend(filtered_l2)
    print(f"[fb_filter] 层2剔除: {len(filtered_l2)} 剩余: {len(after_l2)}", flush=True)

    # 009-010 层3 市场环境
    after_l3, filtered_l3, env_flags = exclude_layer3_market_env(
        after_l2, compact_date, first_boards=first_boards,
    )
    excluded.extend(filtered_l3)
    print(f"[fb_filter] 层3剔除: {len(filtered_l3)} 剩余: {len(after_l3)} "
          f"env={env_flags}", flush=True)

    # 011-021 9 维度评分 + 排序 + 落盘
    print(f"[fb_filter] 开始评分 {len(after_l3)} 只候选...", flush=True)
    scored_candidates = rank_candidates(after_l3, compact_date)
    print(f"[fb_filter] 评分完成: {len(scored_candidates)} 只", flush=True)

    result = {
        "date": compact_date,
        "zt_pool_count": zt_pool_count,
        "first_board_count": first_board_count,
        "candidates": after_l3,
        "scored_candidates": scored_candidates,
        "excluded": excluded,
        "env_flags": env_flags,
    }
    try:
        save_scores(scored_candidates, compact_date, full_result=result)
        print(f"[fb_filter] 落盘完成", flush=True)
    except Exception as e:
        _logger.warning("save_scores 落盘失败 date=%s err=%s", compact_date, e)

    return result


if __name__ == "__main__":
    # 骨架自测：python -m strategies.first_board_filter 20260818
    d = sys.argv[1] if len(sys.argv) > 1 else "20260818"
    result = run_first_board_filter(d)
    print(f"日期: {result['date']}")
    print(f"涨停池: {result['zt_pool_count']}")
    print(f"首板: {result['first_board_count']}")
    print(f"候选: {len(result['candidates'])}")
    print(f"评分后: {len(result.get('scored_candidates', []))}")
    print(f"剔除: {len(result['excluded'])}")
    print(f"env_flags: {result['env_flags']}")
    print("剔除记录（前 10）:")
    for e in result["excluded"][:10]:
        print(f"  L{e['layer']} {e['code']} {e['reason']}")
    print("评分 TOP 5:")
    for c in result.get("scored_candidates", [])[:5]:
        print(f"  #{c['rank']} {c['code']} {c.get('name','')} total={c['total']:.1f}")
        print(f"    scores: {c['scores']}")
