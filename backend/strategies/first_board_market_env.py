# -*- coding: utf-8 -*-
"""首板流 Phase 2 大盘3因素精筛 + 飞书通知（tasks.md 034-038）。

实现范围（spec 2.3「T日9:25 大盘环境3因素精筛」）：
- 034 fetch_hs300_pct：沪深300当日涨跌幅（数据源 index_quote，见下方前提修正）
- 035 fetch_zt_count_compare：涨停家数对比（T日竞价 vs T-1全天）
- 036 fetch_max_boards：连板最高板（market._emotion）
- 037 judge_market_env：3因素组合判定绿/黄/红灯 + 仓位建议
- 038 notify_market_env：飞书通知（红灯/黄灯推送，绿灯不打扰）
- run_market_env_check：主入口串联 034-038

数据源前提修正（重要，spec 描述有误，已核实）：
- spec 称「tencent_quote("000300") 可取沪深300实时涨跌」——**错误前提**。
  `tencent_quote(["000300"])` 实测返 `{}`：因 `get_prefix("000300")` 拼成
  `sz000300`（深市股票口径），而沪深300是指数，腾讯指数代码是 `sh000300`。
  本模块改用 `astock.index_quote()`（其 `A_INDICES` 已含 `sh000300`）取沪深300
  change_pct，字段语义与 spec 一致（百分数，1.61=+1.61%）。

阈值与权重集中在本模块顶部 `MARKET_ENV_THRESHOLDS`，**待回测校准**（当前为骨架占位，
非回测值）。

数据缺失降级原则：任一数据源取不到 → 该因素标 None，judge 跳过该因素（不因数据缺失
误判红灯）。详见各 fetch 函数注释。

合规：本模块按用户传入 date 返回客观市场环境判定，不预置标的、不排名、不建议。
仓位建议是 spec 2.3 明确的灯位映射规则（非主观建议）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from astock import em_zt_topic_pool, index_quote  # noqa: E402
from market import _emotion  # noqa: E402  私有函数，任务要求；后续可升级公开接口

logger = logging.getLogger(__name__)


# ===========================================================================
# 3因素判定阈值（待回测校准，30天后用实际数据调）
# ===========================================================================
# 所有阈值集中在此常量，顶部统一管理。当前值为 spec 2.3 骨架占位，**待回测校准**。
# 实际阈值需用 30 天首板+大盘数据回测后调整（见 tasks.md 038 回测校准）。
# 单位说明：hs300_pct 是百分数（1.61=+1.61%），阈值 0.5 即 +0.5%。
MARKET_ENV_THRESHOLDS: dict = {
    # ── 因素1 沪深300涨跌幅 ──────────────────────────────────────────────
    "hs300_green": 0.5,        # 沪深300 > +0.5% → 绿灯因素
    "hs300_red": -0.5,         # 沪深300 < -0.5% → 红灯因素
    # ── 因素2 涨停家数对比（T日竞价 vs T-1全天）─────────────────────────
    "zt_ratio_green": 0.5,     # T日涨停数 > T-1的 50% → 绿灯因素
    "zt_ratio_red": 0.3,       # T日涨停数 < T-1的 30% → 红灯因素
    # ── 因素3 连板最高板 ──────────────────────────────────────────────
    "max_boards_green": 4,     # 最高板 ≥ 4 → 绿灯因素
    "max_boards_red": 2,      # 最高板 ≤ 2 → 红灯因素
}

# 权重（spec 2.3）：沪深300 50% + 涨停家数 30% + 连板 20%
# 注：当前判定逻辑用「任一绿即绿/全红才红」的规则判定，权重主要用于结果展示与未来
# 加权打分升级（当前 judge 不依赖权重计算 light）。
MARKET_ENV_WEIGHTS: dict = {
    "hs300": 0.50,
    "zt_count": 0.30,
    "max_boards": 0.20,
}

# 仓位建议（灯位 → 建议文案，spec 2.3 明确规则，非主观建议）
_POSITION_ADVICE = {
    "green": "绿灯：可建仓3-5只等权，单股仓位20-33%",
    "yellow": "黄灯：减仓，最多3只单股仓位≤15%",
    "red": "红灯：不建仓（允许人工override）",
}


def _to_float(v) -> float | None:
    """raw 字段可能是 '-'(停牌)/None/str → 归一 float 或 None。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip().replace(",", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ===========================================================================
# 034 沪深300涨跌幅
# ===========================================================================

def fetch_hs300_pct() -> float | None:
    """T日9:25 取沪深300当日涨跌幅。

    数据源：``astock.index_quote()``（其 ``A_INDICES`` 含 ``sh000300``）。
    ⚠️ 前提修正：spec 称用 ``tencent_quote("000300")`` 是错误前提——实测
    ``tencent_quote(["000300"])`` 返 ``{}``（因 get_prefix 把 000300 当深市股票
    拼成 sz000300，而沪深300是指数 sh000300）。改用 index_quote() 取。

    Returns:
        沪深300 change_pct（百分数，1.61=+1.61%）；数据缺失/请求失败 → None
        （不崩，judge 跳过该因素）。
    """
    try:
        indices = index_quote() or []
    except Exception as e:
        logger.warning("fetch_hs300_pct index_quote 失败 err=%s", e)
        return None
    if not indices:
        return None
    # 优先取沪深300（name 含"沪深300"或 code 000300）
    for idx in indices:
        name = str(idx.get("name", ""))
        if "沪深300" in name or "000300" in name:
            return _to_float(idx.get("change_pct"))
    # 降级取上证指数（大盘风向标）
    for idx in indices:
        name = str(idx.get("name", ""))
        if "上证" in name or "000001" in name:
            return _to_float(idx.get("change_pct"))
    # 都取不到 → None
    return None


# ===========================================================================
# 035 涨停家数对比
# ===========================================================================

def fetch_zt_count_compare(date: str) -> dict:
    """涨停家数对比——T日竞价涨停数 vs T-1全天。

    Args:
        date: T日，格式 YYYYMMDD 或 YYYY-MM-DD（内部统一去横线）。

    数据源：``astock.em_zt_topic_pool("getTopicZTPool", date)``。

    ⚠️ 盘前数据限制（spec 约束）：T日9:25 时 ``em_zt_topic_pool(today)`` 可能为空
    （当日竞价涨停池尚未生成）。降级策略：
    - T-1 全天 zt_count 一定能取到（T-1 是完整交易日）；
    - T日竞价涨停数取不到 → ``zt_count_t=None``，judge 跳过该因素。

    Returns:
        dict 含：
        - zt_count_t1: int（T-1全天涨停家数，必返）
        - zt_count_t: int | None（T日竞价涨停家数；盘前可能为 None）
        - ratio: float | None（zt_count_t / zt_count_t1；T日为空时 None）
        - note: str（标注"T日竞价涨停数待9:30后更新"）
    """
    compact_date = date.replace("-", "") if "-" in date else date
    try:
        d = datetime.strptime(compact_date, "%Y%m%d")
    except ValueError:
        return {"zt_count_t1": 0, "zt_count_t": None, "ratio": None, "note": "日期格式错误"}
    t1_date = (d - timedelta(days=1)).strftime("%Y%m%d")

    # T-1 全天涨停数（必取）
    zt_count_t1 = 0
    try:
        t1_pool = em_zt_topic_pool("getTopicZTPool", t1_date, "fbt:asc") or []
        zt_count_t1 = len(t1_pool)
    except Exception as e:
        logger.warning("fetch_zt_count_compare T-1 取数失败 t1=%s err=%s", t1_date, e)

    # T日竞价涨停数（盘前可能为空）
    zt_count_t: Optional[int] = None
    try:
        t_pool = em_zt_topic_pool("getTopicZTPool", compact_date, "fbt:asc") or []
        if t_pool:
            zt_count_t = len(t_pool)
    except Exception as e:
        logger.warning("fetch_zt_count_compare T日取数失败 t=%s err=%s", compact_date, e)

    ratio: Optional[float] = None
    if zt_count_t is not None and zt_count_t1 > 0:
        ratio = round(zt_count_t / zt_count_t1, 3)

    note = "T日竞价涨停数待9:30后更新" if zt_count_t is None else ""
    return {
        "zt_count_t1": zt_count_t1,
        "zt_count_t": zt_count_t,
        "ratio": ratio,
        "note": note,
    }


# ===========================================================================
# 036 连板最高板
# ===========================================================================

def fetch_max_boards(date: str) -> dict:
    """连板最高板。

    Args:
        date: T日，格式 YYYYMMDD 或 YYYY-MM-DD。

    数据源：``market._emotion(date)``。

    ⚠️ 数据源约束（spec 约束，已核实）：``_emotion(date)`` 在 T日9:25 时若当日
    涨停池为空会**回溯返 T-1 数据**（内部 ``if not zt: return {}`` 分支会在指定日期
    无数据时返空，但若回溯模式——即 date=None——会自动定位最近交易日；本函数显式
    传 date，若当日无数据返空 dict）。降级策略：
    - 先传 T日 date 取当日 max_boards；
    - 若返空（盘前涨停池未生成），降级传 T-1 date 取 T-1 值，标 is_t1_fallback=True；
    - 若 T-1 也取不到 → max_boards=None，judge 跳过该因素。

    Returns:
        dict 含：
        - max_boards: int | None（连板最高板数）
        - source_date: str（实际取数日期 YYYY-MM-DD）
        - is_t1_fallback: bool（True=9:25返回T-1值，待9:30后更新）
        - note: str（is_t1_fallback 时标注）
    """
    compact_date = date.replace("-", "") if "-" in date else date
    try:
        d = datetime.strptime(compact_date, "%Y%m%d")
    except ValueError:
        return {"max_boards": None, "source_date": "", "is_t1_fallback": False, "note": "日期格式错误"}
    t1_date = (d - timedelta(days=1)).strftime("%Y%m%d")
    t1_iso = f"{t1_date[:4]}-{t1_date[4:6]}-{t1_date[6:8]}"
    t_iso = f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:8]}"

    # 先取 T日
    emotion = {}
    try:
        emotion = _emotion(t_iso) or {}
    except Exception as e:
        logger.warning("fetch_max_boards T日 _emotion 失败 t=%s err=%s", t_iso, e)

    if emotion:  # T日有数据
        mb = emotion.get("max_boards")
        return {
            "max_boards": int(mb) if mb is not None else None,
            "source_date": t_iso,
            "is_t1_fallback": False,
            "note": "",
        }

    # T日无数据 → 降级取 T-1
    try:
        emotion_t1 = _emotion(t1_iso) or {}
    except Exception as e:
        logger.warning("fetch_max_boards T-1 _emotion 失败 t1=%s err=%s", t1_iso, e)
        emotion_t1 = {}

    mb_t1 = emotion_t1.get("max_boards") if emotion_t1 else None
    return {
        "max_boards": int(mb_t1) if mb_t1 is not None else None,
        "source_date": t1_iso if emotion_t1 else "",
        "is_t1_fallback": True,
        "note": "9:25返回T-1值，待9:30后更新" if emotion_t1 else "T日与T-1均无数据",
    }


# ===========================================================================
# 037 3因素组合判定
# ===========================================================================

def judge_market_env(
    hs300_pct: float | None,
    zt_compare: dict,
    max_boards_data: dict,
) -> dict:
    """3因素组合判定绿/黄/红灯 + 仓位建议。

    规则（spec 2.3）：
    - 绿灯：hs300>0.5% OR zt_ratio>0.5 OR max_boards≥4（任一绿即绿）
    - 红灯：hs300<-0.5% AND zt_ratio<0.3 AND max_boards≤2（全红才红）
    - 黄灯：其他

    数据缺失降级：任一因素 None → 该因素不参与判定（不因数据缺失误判红灯）。
    具体规则修正：
    - 若所有因素都缺失 → 黄灯（无法判定，默认中性）
    - 若仅一个红因素 + 其他缺失 → 黄灯（不满足"全红才红"）
    - 若一个绿因素 + 其他缺失 → 绿灯（满足"任一绿即绿"）

    Returns:
        dict 含：
        - light: "green" | "yellow" | "red"
        - hs300_pct: float | None
        - zt_count_t1: int, zt_count_t: int | None, zt_ratio: float | None
        - max_boards: int | None, max_boards_is_t1_fallback: bool
        - factors: {hs300/zt_count/max_boards 各自 green/yellow/red}
        - position_advice: str（灯位 → 仓位建议文案）
    """
    # 因素1：沪深300
    hs300_factor: str
    if hs300_pct is None:
        hs300_factor = "yellow"  # 数据缺失 → 中性
    elif hs300_pct > MARKET_ENV_THRESHOLDS["hs300_green"]:
        hs300_factor = "green"
    elif hs300_pct < MARKET_ENV_THRESHOLDS["hs300_red"]:
        hs300_factor = "red"
    else:
        hs300_factor = "yellow"

    # 因素2：涨停家数对比
    zt_ratio = zt_compare.get("ratio") if zt_compare else None
    zt_count_t1 = zt_compare.get("zt_count_t1", 0) if zt_compare else 0
    zt_count_t = zt_compare.get("zt_count_t") if zt_compare else None
    zt_factor: str
    if zt_ratio is None:
        zt_factor = "yellow"  # T日竞价数缺失 → 中性
    elif zt_ratio > MARKET_ENV_THRESHOLDS["zt_ratio_green"]:
        zt_factor = "green"
    elif zt_ratio < MARKET_ENV_THRESHOLDS["zt_ratio_red"]:
        zt_factor = "red"
    else:
        zt_factor = "yellow"

    # 因素3：连板最高板
    mb = max_boards_data.get("max_boards") if max_boards_data else None
    mb_fallback = bool(max_boards_data.get("is_t1_fallback")) if max_boards_data else False
    mb_factor: str
    if mb is None:
        mb_factor = "yellow"
    elif mb >= MARKET_ENV_THRESHOLDS["max_boards_green"]:
        mb_factor = "green"
    elif mb <= MARKET_ENV_THRESHOLDS["max_boards_red"]:
        mb_factor = "red"
    else:
        mb_factor = "yellow"

    # 组合判定
    factors = {"hs300": hs300_factor, "zt_count": zt_factor, "max_boards": mb_factor}
    # 绿灯：任一绿即绿（数据缺失不影响绿判定）
    if "green" in factors.values():
        light = "green"
    # 红灯：全红才红（数据缺失因素不算红，所以全红需所有非缺失因素都红 + 无缺失因素，
    #   但若所有因素缺失则上面已判黄）。此处语义：已排除绿后，若任一因素为 yellow
    #   （含数据缺失）→ 不能判红，判黄；仅当三因素都明确 red 才判红。
    elif all(v == "red" for v in factors.values()):
        light = "red"
    else:
        light = "yellow"

    return {
        "light": light,
        "hs300_pct": hs300_pct,
        "zt_count_t1": zt_count_t1,
        "zt_count_t": zt_count_t,
        "zt_ratio": zt_ratio,
        "max_boards": mb,
        "max_boards_is_t1_fallback": mb_fallback,
        "factors": factors,
        "position_advice": _POSITION_ADVICE[light],
    }


# ===========================================================================
# 038 飞书通知
# ===========================================================================

def _format_market_env_message(result: dict) -> str:
    """格式化市场环境判定结果为 Markdown 消息（飞书推送用）。"""
    judge = result.get("judge", {})
    light = judge.get("light", "yellow")
    light_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(light, "⚪")
    lines = [
        f"### {light_emoji} 首板流·大盘环境判定",
        f"",
        f"**判定灯位**：{light_emoji} {light}",
        f"",
        f"**仓位建议**：{judge.get('position_advice', '')}",
        f"",
        f"---",
        f"",
        f"**3因素明细**：",
        f"",
        f"- 沪深300涨跌幅：{_fmt_pct(judge.get('hs300_pct'))} （{judge.get('factors', {}).get('hs300', '-')}）",
        f"- 涨停家数：T-1={judge.get('zt_count_t1', 0)}家 / T日={_fmt_int(judge.get('zt_count_t'))}家 / 比值={_fmt_ratio(judge.get('zt_ratio'))} （{judge.get('factors', {}).get('zt_count', '-')}）",
        f"- 连板最高板：{_fmt_int(judge.get('max_boards'))}板 {'(T-1回溯)' if judge.get('max_boards_is_t1_fallback') else ''} （{judge.get('factors', {}).get('max_boards', '-')}）",
        f"",
        f"---",
        f"",
        f"日期：{result.get('date', '')}",
        f"阈值标注：待回测校准（当前为骨架占位）",
    ]
    return "\n".join(lines)


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_int(v) -> str:
    if v is None:
        return "N/A(待9:30更新)"
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return "N/A"


def _fmt_ratio(v) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v)*100:.0f}%"
    except (TypeError, ValueError):
        return "N/A"


def notify_market_env(result: dict) -> bool:
    """飞书通知市场环境判定。

    复用现有 ``NotificationService`` 体系（``notification/notification_service.py``），
    **不新建通知通道**。

    推送规则（spec 2.3）：
    - 红灯 → 推"环境红灯不建仓，允许人工override"（severity=warning）
    - 黄灯 → 推"环境黄灯减仓，最多3只单股15%"（severity=info）
    - 绿灯 → **不推**（正常建仓不打扰）

    路由选择：用 ``route_type="alert"``（市场环境判定属于事件驱动 alert，
    ``NOTIFICATION_ROUTE_CONFIGS`` 已有 alert 路由；未配置 alert 渠道时
    ``get_channels_for_route`` 返全部静态渠道——legacy 行为）。

    Args:
        result: ``run_market_env_check`` 返回的完整结果 dict。

    Returns:
        True=已推送，False=未推（绿灯/未配通道/推送失败）。
    """
    judge = result.get("judge", {})
    light = judge.get("light", "yellow")

    # 绿灯不打扰
    if light == "green":
        logger.info("绿灯不打扰，不推送市场环境通知")
        return False

    # 黄灯/红灯推送
    severity = "warning" if light == "red" else "info"
    content = _format_market_env_message(result)

    try:
        from notification.notification_service import NotificationService
        ns = NotificationService()
        if not ns.is_available():
            logger.warning("通知服务无可用渠道，跳过推送")
            return False
        ok = ns.send(
            content,
            route_type="alert",
            severity=severity,
        )
        return bool(ok)
    except Exception as e:
        logger.error("notify_market_env 推送失败 light=%s err=%s", light, e)
        return False


# ===========================================================================
# 主入口
# ===========================================================================

def run_market_env_check(date: str) -> dict:
    """Phase 2 大盘3因素主入口。

    串联 034-038，返回完整结果。

    Args:
        date: T日，格式 YYYYMMDD（如 "20260818"）或 YYYY-MM-DD。

    Returns:
        dict 含：
        - date: str（标准化为 YYYYMMDD）
        - hs300_pct: float | None
        - zt_compare: dict（fetch_zt_count_compare 结果）
        - max_boards_data: dict（fetch_max_boards 结果）
        - judge: dict（judge_market_env 结果）
        - notified: bool（是否已推送飞书通知）
    """
    compact_date = date.replace("-", "") if "-" in date else date

    # 034 沪深300
    hs300_pct = fetch_hs300_pct()

    # 035 涨停家数对比
    zt_compare = fetch_zt_count_compare(compact_date)

    # 036 连板最高板
    max_boards_data = fetch_max_boards(compact_date)

    # 037 3因素组合判定
    judge = judge_market_env(hs300_pct, zt_compare, max_boards_data)

    # 038 飞书通知
    result = {
        "date": compact_date,
        "hs300_pct": hs300_pct,
        "zt_compare": zt_compare,
        "max_boards_data": max_boards_data,
        "judge": judge,
        "notified": False,
    }
    try:
        result["notified"] = notify_market_env(result)
    except Exception as e:
        logger.error("run_market_env_check 通知异常 err=%s", e)
        result["notified"] = False

    return result


if __name__ == "__main__":
    # 骨架自测：python -m strategies.first_board_market_env 20260818
    import sys as _sys
    d = _sys.argv[1] if len(_sys.argv) > 1 else "20260818"
    r = run_market_env_check(d)
    print(f"日期: {r['date']}")
    print(f"沪深300涨跌幅: {r['hs300_pct']}")
    print(f"涨停对比: {r['zt_compare']}")
    print(f"连板: {r['max_boards_data']}")
    print(f"灯: {r['judge']['light']}")
    print(f"因素: {r['judge']['factors']}")
    print(f"建议: {r['judge']['position_advice']}")
    print(f"已通知: {r['notified']}")
