# -*- coding: utf-8 -*-
"""universe——涨停池/首板过滤/市场档位判定。

实现范围：
- 003 数据层：fetch_zt_pool / filter_first_board
- 市场档位：_market_phase / PHASE_TO_CAP_TIER
- 辅助：_to_float / _fbt_to_hhmm
- 阈值常量：EXCLUDE_THRESHOLDS / MARKET_PHASE_WEIGHTS

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

import logging
from typing import Optional

from astock import em_zt_topic_pool, concept_blocks  # noqa: E402
from market import _emotion  # noqa: E402  私有函数，任务要求；后续可升级公开接口

_logger = logging.getLogger(__name__)


# ===========================================================================
# 阈值配置（待回测校准，30 天后用实际数据调）
# ===========================================================================
# 所有阈值集中在此常量，顶部统一管理。当前值为骨架占位，非回测校准值。
# 标注"待回测校准"：实际阈值需用 30 天首板数据回测后调整（见 tasks.md 021 回测校准）。
EXCLUDE_THRESHOLDS: dict = {
    # ── 硬剔除底线（grill 收紧：只留"绝对不能买"2 条，待回测校准）─────────
    "max_break_times": 2,          # 炸板次数 ≥2 剔除（封板不牢）
    "min_seal_ratio": 0.001,        # 封单/流通市值 <0.1% 剔除（封单太薄）
    # 移除的（改为评分维度，不再硬剔除）：
    # "max_turnover": 30.0,          # 移除，改 score_dim_turnover 倒U型评分
    # "late_seal_time": 140000,      # 改为 score_dim_seal_time 评分
    # "max_amount_yi": 15.0,         # 改为 chip 评分体现
    # "max_vol_ratio": 2.0,          # 改为 chip 评分体现
    # ── 层3 改纯环境标记（不剔除，只输出 env_flags 供评分权重分层用）────────
    "exclude_isolated_board": False,  # 孤板不硬剔除，改评分（grill 收紧）
    "exclude_chinext": False,       # 创业板不剔除（候选池按板块分组排序区分展示）
    "market_drop_threshold": -1.5,  # 大盘跌 >1.5% 标记高风险（不剔除，仅标记）
    "min_sector_zt_count": 2,       # 保留但只做评分参考，不剔除
}


# ===========================================================================
# 评分权重分层（按 zt_count 市场状态分层，待回测校准）
# ===========================================================================
# grill 锁定决策：权重按 zt_count 4 档分层（冰点/普通/活跃/亢奋）。
# 数据缺失维度 score=-1 不参与加权，权重重分配到其他有效维度。
MARKET_PHASE_WEIGHTS: dict[str, dict[str, float]] = {
    "冰点": {  # zt<30：封板质量主导（seal_time+seal_ratio=0.55），板块联动弱
        "seal_time": 0.25, "sector_link": 0.10, "market_cap": 0.20,
        "seal_ratio": 0.30, "turnover": 0.15,
    },
    "普通": {  # 30-60：均衡
        "seal_time": 0.20, "sector_link": 0.20, "market_cap": 0.15,
        "seal_ratio": 0.30, "turnover": 0.15,
    },
    "活跃": {  # 60-100：板块联动权重提升
        "seal_time": 0.15, "sector_link": 0.30, "market_cap": 0.10,
        "seal_ratio": 0.30, "turnover": 0.15,
    },
    "亢奋": {  # zt>=100：板块联动主导（接力情绪强）
        "seal_time": 0.10, "sector_link": 0.40, "market_cap": 0.10,
        "seal_ratio": 0.25, "turnover": 0.15,
    },
}


def _market_phase(
    zt_count: int | None,
    big_loss: int | None = None,
    floor: int | None = None,
    ladder_success: float | None = None,
    ladder_height: int | None = None,
) -> str:
    """按涨停家数 + 市场风险因子判定市场档位。

    S079 R6 扩展：从单因子 zt_count 改为 4 因子输入 + 红期硬熔断覆盖。

    档位：冰点 / 普通 / 活跃 / 亢奋 / 红期
      - 红期硬熔断覆盖（优先级最高）：big_loss≥8 或 floor≥20 → "红期"
      - 四档判定（原逻辑保留）：zt_count <30→冰点 / <60→普通 / <100→活跃 / ≥100→亢奋

    因子含义（spec R6.1，T-1 盘后数据计算）：
      zt_count: 涨停家数（保留，既有）
      big_loss: 大面股≥10% 家数（big_loss_count）
      floor: 跌停家数（floor_count）
      ladder_success: 连板晋级率（ladder_success_rate）
      ladder_height: 连板最高高度（max_ladder_height）

    向后兼容（R6.5）：旧签名 `_market_phase(zt_count)` 调用走原四档判定
      （big_loss/floor/ladder_success/ladder_height 均为 None → 跳过红期硬熔断），
      `score_candidate`（line ~1350）现有调用不破坏。

    时序用途（R8，文档层声明）：
      STI 是 T-1 盘后总结（limitup_sti 8 维度加权 → 4 天气），用于 PositionAdvisor.advise
      的 weather_state 参数；_market_phase 是 T+1 盘前仓位闸因子，用于
      position_advisor.cap_by_market_phase 的 phase 参数。两者时序用途不同，
      不引入新概念，不替代 STI。
    """
    # R6.2 红期硬熔断覆盖（优先级最高）
    if big_loss is not None and big_loss >= 8:
        return "红期"
    if floor is not None and floor >= 20:
        return "红期"

    # R6.1 四档判定（原逻辑保留）
    if zt_count is None:
        return "普通"
    if zt_count < 30:
        return "冰点"
    if zt_count < 60:
        return "普通"
    if zt_count < 100:
        return "活跃"
    return "亢奋"


# R6.3 三状态映射常量（供 position_advisor.cap_by_market_phase 使用）
# 绿 = 活跃 + 亢奋 / 黄 = 普通 / 红 = 冰点 或 红期硬熔断覆盖触发
PHASE_TO_CAP_TIER: dict[str, str] = {
    "活跃": "green",
    "亢奋": "green",
    "普通": "yellow",
    "冰点": "red",
    "红期": "red",
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

    S205: 历史日优先 zt_history snapshot fallback——em_get 实时涨停池当日，
    历史日无；zt_history（.vibe-research/zt_history.db）存历史 snapshot（33 天~积累）。
    解锁 forward_test 历史日 picks（pool_map 非空 → storm_reversal 战法 match 命中）。
    zt_history 字段 code/name 转成 em_get c/n 格式（score_candidates pool_map 读 c）。
    """
    compact = date.replace("-", "") if "-" in date else date
    # S205: 历史日优先 zt_history snapshot fallback
    try:
        from vr_paths import resolve_data_dir  # noqa: PLC0415
        import sqlite3  # noqa: PLC0415
        zt_db = resolve_data_dir() / "zt_history.db"
        if zt_db.exists():
            conn = sqlite3.connect(str(zt_db))
            try:
                rows = conn.execute(
                    "SELECT code,name,lbc,zbc,fbt,fund,zje,p,ltsz,fundamt,hybk "
                    "FROM zt_history WHERE date=? AND is_final=1",
                    (date,),
                ).fetchall()
                if rows:
                    # zt_history code/name → em_get c/n 格式（pool_map 读 c）
                    cols = ["c", "n", "lbc", "zbc", "fbt", "fund", "zje", "p", "ltsz", "fundamt", "hybk"]
                    return [dict(zip(cols, r)) for r in rows]
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001
        _logger.warning("fetch_zt_pool zt_history fallback 失败 date=%s err=%s", date, e)
    # 当日 or zt_history 无 → em_get 实时
    try:
        # S131 R5：raise_on_failure=True 让源断 raise（非吞 [] 伪装空池），
        # try/except 兜底返 []（上层 run_first_board_filter 走空候选降级）。
        return em_zt_topic_pool("getTopicZTPool", compact, "fbt:asc", raise_on_failure=True) or []
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
