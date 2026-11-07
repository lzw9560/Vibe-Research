"""Project-local path helpers for Vibe-Research private data.

约束（用户 2026-07-30 指令，覆盖 CLAUDE.md §1 旧"~/.vibe-research/"约定）：
所有项目相关信息只存项目目录内，不落到 home 目录。私有数据（API key /
持仓 / 研报）放入项目根的 ``.vibe-research/``（gitignored，绝不进 git）。

仍可用 ``VR_DATA_DIR`` / ``VR_REPORTS_DIR`` 环境变量覆盖（测试时 conftest
会指到临时目录隔离）。
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/vr_paths.py → 上一级即仓库根
_REPO_ROOT: Path = Path(__file__).resolve().parents[1]

#: 项目内私有数据根目录（gitignored，绝不进 git）
DEFAULT_DATA_DIR: Path = _REPO_ROOT / ".vibe-research"


def resolve_data_dir() -> Path:
    """返回生效的私有数据根目录：优先 ``$VR_DATA_DIR``，否则项目内默认。

    防 home 分裂：VR_DATA_DIR 若指向 home 目录（~/...），fallback 到项目根
    .vibe-research（生产不应写 home；测试 conftest 临时目录非 home 不受影响）。
    """
    env = os.environ.get("VR_DATA_DIR")
    if env:  # 空串视同未设置
        p = Path(env).expanduser()
        # 防 home 分裂：仅当 env 指向 home 直接子目录（如 ~/.vibe-research）→ fallback 项目根
        # 项目 .vibe-research 虽在 home 下但是项目子目录（合法），不误判；测试临时目录非 home 不受影响
        if p.parent == Path.home() or p == Path.home() / ".vibe-research":
            import logging

            logging.getLogger("vibe-research").warning("[vr_paths] VR_DATA_DIR=%s 在 home 根下，fallback 项目根 .vibe-research（防分裂）", env)
            return DEFAULT_DATA_DIR
        return p
    return DEFAULT_DATA_DIR


def resolve_reports_dir() -> Path:
    """返回研报目录：优先 ``$VR_REPORTS_DIR``，否则 data_dir/myreports。"""
    env = os.environ.get("VR_REPORTS_DIR")
    if env:
        return Path(env)
    return resolve_data_dir() / "myreports"


# ---------- 交易日判断（S023 C1）----------

from datetime import date, datetime as _dt, time as _time, timedelta as _td, timezone as _tz
import json
import logging

#: 北京时区 UTC+8——所有"当前时刻"判断统一用此，杜绝 naive datetime 时区 bug
BEIJING_TZ = _tz(_td(hours=8))

#: 交易日历缓存文件路径（与 calendar_factor.py 共用，由 scripts/refresh_trade_calendar.py 刷新）
_HOLIDAYS_JSON_PATH: Path = Path(__file__).resolve().parent / "data" / "holidays.json"

#: 缓存过期阈值（天）——超过此天数视为过期，触发 akshare 刷新
_HOLIDAYS_CACHE_MAX_AGE_DAYS = 30

#: A 股法定节假日硬编码 fallback（YYYY-MM-DD）。仅列工作日休市日（周末由 weekday 判断覆盖）。
#: 用途：holidays.json 不存在/损坏/akshare 拉取失败时的最后兜底。
#: 注意：akshare tool_trade_date_hist_sina 数据通常只到当年末，次年节假日须次年放假安排公布后补充。
#: 2027-01-01 元旦已预先加入（akshare 当前无 2027 数据，元旦是固定节假日，可预先标）。
_A_SHARE_HOLIDAYS_FALLBACK: set[str] = {
    # 2026 元旦
    "2026-01-01",
    # 2026 春节
    "2026-02-16",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-02-20",
    # 2026 清明
    "2026-04-06",
    # 2026 劳动节
    "2026-05-04",
    "2026-05-05",
    "2026-05-06",
    # 2026 端午
    "2026-06-19",
    # 2026 中秋
    "2026-09-25",
    # 2026 国庆
    "2026-10-01",
    "2026-10-02",
    "2026-10-05",
    "2026-10-06",
    "2026-10-07",
    "2026-10-08",
    # 2027 元旦（固定节假日，akshare 当前无 2027 数据，预先标以防次年误判）
    "2027-01-01",
}

#: 加载后的节假日集合（模块级缓存，首次调用 is_trading_day 时懒加载）
_A_SHARE_HOLIDAYS: set[str] | None = None

_logger = logging.getLogger("vibe-research")


def _is_holidays_cache_fresh(meta: dict) -> bool:
    """判断 holidays.json 的 _meta.updated 是否在 30 天内。

    缓存新鲜度判据：``_meta.updated`` 字段距今天 <= _HOLIDAYS_CACHE_MAX_AGE_DAYS 天。
    缺字段视为过期（触发刷新）。
    """
    updated_str = meta.get("updated")
    if not updated_str:
        return False
    try:
        updated_date = date.fromisoformat(str(updated_str)[:10])
    except ValueError:
        return False
    age_days = (date.today() - updated_date).days
    return age_days <= _HOLIDAYS_CACHE_MAX_AGE_DAYS


def _load_holidays_from_json() -> set[str] | None:
    """从 holidays.json 加载 non_trading_days 字段。

    返回 None 表示文件不存在/损坏/缺字段/已过期（调用方应尝试 akshare 刷新或 fallback）。
    缓存过期不在此刷新——此函数只做"读缓存"，刷新逻辑在 _ensure_holidays_loaded。
    """
    if not _HOLIDAYS_JSON_PATH.exists():
        return None
    try:
        data = json.loads(_HOLIDAYS_JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("[vr_paths] holidays.json 解析失败: %s，将 fallback 硬编码", e)
        return None
    meta = data.get("_meta", {}) or {}
    if not _is_holidays_cache_fresh(meta):
        _logger.info(
            "[vr_paths] holidays.json 缓存已过期（updated=%s），将尝试 akshare 刷新",
            meta.get("updated"),
        )
        return None
    days = data.get("non_trading_days")
    if not isinstance(days, list) or not days:
        return None
    return {str(d) for d in days}


def _refresh_holidays_via_akshare() -> bool:
    """用 akshare 拉取最新交易日历并写入 holidays.json。

    成功返回 True，失败返回 False（调用方 fallback 到硬编码）。
    与 scripts/refresh_trade_calendar.py 共用同一逻辑。
    """
    try:
        import akshare as ak  # 延迟导入，避免模块加载时触发网络
    except ImportError:
        _logger.warning("[vr_paths] akshare 未安装，无法自动刷新交易日历")
        return False
    try:
        df = ak.tool_trade_date_hist_sina()
        trade_days = set(str(d) for d in df["trade_date"])
    except Exception as e:
        _logger.warning("[vr_paths] akshare 拉取交易日历失败: %s，将 fallback 硬编码", e)
        return False

    # 反推工作日休市日（近 2 年）
    years_with_data = sorted({d[:4] for d in trade_days})
    target_years = years_with_data[-2:]
    non_trading: list[str] = []
    from datetime import timedelta as _td_inner

    for y in target_years:
        cur = date(int(y), 1, 1)
        end = date(int(y), 12, 31)
        while cur <= end:
            if cur.weekday() < 5 and cur.isoformat() not in trade_days:
                non_trading.append(cur.isoformat())
            cur += _td_inner(days=1)

    # 读现有 JSON 保留 calendar_factor 依赖的字段，只更新 non_trading_days + _meta
    try:
        if _HOLIDAYS_JSON_PATH.exists():
            data = json.loads(_HOLIDAYS_JSON_PATH.read_text(encoding="utf-8"))
        else:
            data = {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data.setdefault("_meta", {})
    data["_meta"]["updated"] = date.today().isoformat()
    data["_meta"]["source"] = "akshare tool_trade_date_hist_sina + 国务院放假安排"
    if non_trading:
        years = sorted({d[:4] for d in non_trading})
        data["_meta"]["trade_calendar_range"] = f"{years[0]}-{years[-1]}"
    data["non_trading_days"] = non_trading
    try:
        _HOLIDAYS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HOLIDAYS_JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _logger.info("[vr_paths] 已用 akshare 刷新 holidays.json（%d 个工作日休市日）", len(non_trading))
        return True
    except OSError as e:
        _logger.warning("[vr_paths] holidays.json 写入失败: %s，将 fallback 硬编码", e)
        return False


def _ensure_holidays_loaded() -> set[str]:
    """懒加载节假日集合，优先级：holidays.json 缓存 > akshare 刷新 > 硬编码 fallback。

    返回最终生效的节假日 set（已缓存到模块级 _A_SHARE_HOLIDAYS）。
    三级降级保证：
    1. holidays.json 存在且未过期 → 直接加载 non_trading_days
    2. 过期/缺失 → akshare 拉取并写回 holidays.json，再加载
    3. akshare 失败 → 仅用硬编码 _A_SHARE_HOLIDAYS_FALLBACK

    关键设计：JSON 缓存与硬编码 fallback **取并集**，而非二选一。原因——
    akshare 交易日历通常只到当年末，次年节假日（如 2027 元旦）须靠硬编码覆盖。
    JSON 的 non_trading_days 是"近期已确认休市日"，硬编码是"长期固定节假日兜底"，
    两者覆盖不同时间范围，并集才能既准确（近期）又不漏（远期固定节假日）。
    """
    global _A_SHARE_HOLIDAYS
    if _A_SHARE_HOLIDAYS is not None:
        return _A_SHARE_HOLIDAYS

    # 始终以硬编码 fallback 为基底（覆盖 JSON 数据范围外的固定节假日，如 2027 元旦）
    merged: set[str] = set(_A_SHARE_HOLIDAYS_FALLBACK)

    # 1. 尝试从缓存加载并合并
    cached = _load_holidays_from_json()
    if cached is not None:
        merged |= cached
        _A_SHARE_HOLIDAYS = merged
        return _A_SHARE_HOLIDAYS

    # 2. 缓存过期/缺失 → akshare 刷新
    if _refresh_holidays_via_akshare():
        refreshed = _load_holidays_from_json()
        if refreshed is not None:
            merged |= refreshed
            _A_SHARE_HOLIDAYS = merged
            return _A_SHARE_HOLIDAYS

    # 3. akshare 也失败 → 仅用硬编码兜底（merged 已是 fallback）
    _logger.warning(
        "[vr_paths] 交易日历缓存与 akshare 刷新均失败，使用硬编码 fallback（%d 个节假日）",
        len(merged),
    )
    _A_SHARE_HOLIDAYS = merged
    return _A_SHARE_HOLIDAYS


def is_trading_day(d: date | None = None) -> bool:
    """判断是否 A 股交易日（周一至周五且非法定节假日）。

    实现细节（2026-11-07 修复硬编码过期问题）：
    - 节假日来源三级降级：holidays.json 缓存 → akshare 刷新 → 硬编码 fallback。
    - holidays.json 由 scripts/refresh_trade_calendar.py 维护，含 non_trading_days 字段
      （工作日休市日，周末由 weekday 判断覆盖不重复列）。
    - 调休补班日（周末补班）未纳入，量级极小且偶发，非交易日时因子会用上一交易日，影响可忽略。
    - d 可传 ``date`` 对象或 ``YYYY-MM-DD`` 字符串（字符串内部转 date，向后兼容调用方）。
    """
    if d is None:
        d = date.today()
    elif isinstance(d, str):
        # 容忍字符串输入（YYYY-MM-DD），转 date 后判断
        try:
            d = date.fromisoformat(d)
        except ValueError:
            return False  # 非法日期字符串保守判非交易日
    if d.weekday() >= 5:  # 周六 5 / 周日 6
        return False
    holidays = _ensure_holidays_loaded()
    return d.isoformat() not in holidays


#: A 股盘中交易时段（S103 下沉自 seal_intraday_collector，供 data/sources 复用避免循环 import）
#: 09:25-11:30（含集合竞价尾 + 上午盘）/ 13:01-15:05（下午盘含收盘竞价）
INTRADAY_PERIODS: list[tuple[_time, _time]] = [
    (_time(9, 25), _time(11, 30)),
    (_time(13, 1), _time(15, 5)),
]

#: A 股集合竞价窗口（S167 竞价累积）。09:25 为集合 match 时刻，含在窗口内
#: （live 9:15-9:25 演化 + 9:25 match 终态）。与 INTRADAY_PERIODS 仅在 9:25 边界相接。
AUCTION_PERIODS: list[tuple[_time, _time]] = [
    (_time(9, 15), _time(9, 25)),
]


def is_intraday_time(now: _dt | None = None) -> bool:
    """是否在盘中交易时段（交易日 + 09:25-11:30 / 13:01-15:05）。

    S103：盘中时段判断基础设施级函数。组合 is_trading_day(当前日期) +
    当前时刻在 INTRADAY_PERIODS 内。供 em_zt_topic_pool 缓存 TTL 判定 +
    seal_intraday_collector 复用（消除 data/sources → risk 反向依赖）。
    """
    now = now or _dt.now()
    if not is_trading_day(now.date()):
        return False
    t = now.time()
    return any(s <= t <= e for s, e in INTRADAY_PERIODS)


def is_auction_time(now: _dt | None = None) -> bool:
    """是否在集合竞价窗口（交易日 + 09:15-09:25）。

    S167 竞价累积：竞价是 §44 reframe 标记的最未证否盘中 edge（S152/S156 证否
    封板时间/秒板，但未证否竞价量比）。供 intraday_microstructure_snapshot 在
    09:15-09:25 也放行采集 live 竞价演化（与 is_intraday_time 09:25+ 不重叠，
    仅 9:25 边界相接）。非交易日返 False。
    """
    now = now or _dt.now()
    if not is_trading_day(now.date()):
        return False
    t = now.time()
    return any(s <= t <= e for s, e in AUCTION_PERIODS)


def last_trading_date(d: date | None = None) -> date:
    """返回 d 当日或之前的最近 A 股交易日。

    - 非交易时段（周末/节假日/盘后）回退到最近交易日。
    - d 为交易日则返回 d 本身；否则向前回溯直到交易日。
    """
    d = d or date.today()
    while not is_trading_day(d):
        d = d - _td(days=1)
    return d


def prev_trading_date(d: date | None = None) -> date:
    """返回 d 之前（不含 d）的最近交易日——严格前一交易日。

    last_trading_date(d) 在 d 为交易日时返回 d 本身，故"前一交易日"须先退一日
    再回退过周末/节假日，否则取到当日。S088 grill Q1：predict_storm 预测交易日
    时须读前一交易日的夜间快照，而非当日快照。
    """
    d = d or date.today()
    return last_trading_date(d - _td(days=1))


def last_trading_date_str(d: date | None = None) -> str:
    """返回 last_trading_date 的 YYYY-MM-DD 字符串。"""
    return last_trading_date(d).isoformat()


def prev_trading_date_str(d: date | None = None) -> str:
    """返回 prev_trading_date 的 YYYY-MM-DD 字符串（严格前一交易日，S117）。"""
    return prev_trading_date(d).isoformat()


def next_trading_date(d: date | None = None) -> date:
    """返回 d 之后（不含 d）的最近交易日——严格后一交易日。

    与 ``prev_trading_date`` 对称。S092 R8a：手动回看时前瞻=F 的下一交易日
    （周五→周一、节前→节后），非日历 +1。
    """
    d = d or date.today()
    d = d + _td(days=1)
    while not is_trading_day(d):
        d = d + _td(days=1)
    return d


def resolve_date_triplet(date_override: date | None = None) -> dict:
    """S092 R9：交易日锚 F + 时段推断三视图日期三元组。

    纯本地计算（``vr_paths`` + ``datetime.now(BEIJING_TZ)``），零外部请求。
    所有时刻判定用北京时区，杜绝 naive datetime 时区 bug
    （``trading_workflow.py:25`` 踩坑记录）。

    - **F**（交易日锚）：交易日 17:15 后 F=当日；其余 F=上一交易日。
    - **review**（复盘数据日）：交易日 15:30 后独立推进到当日
      （``review_advanced=True``），15:30 前 review=F（S093：盘中延长到 15:30）。
    - **today**（当日数据日）：盘前/集合竞价(pre_open)/盘中=F 的下一交易日
      （今早简报/实时盯盘）；盘后/非交易日=F（简报快照，R4 降级——不臆造 F+1 简报）。
    - **forward**（前瞻数据日）：= F 的下一交易日（非日历 +1，周五→周一）。

    手动 ``date_override`` 覆盖 F（R7），但 stage 仍按当前时刻算、定时器不推进
    （``review_advanced=False``）。R8a 特例：过渡窗内手动选"今天"（== 今日交易日）
    等价于不选，复用自动态（防前瞻拿到陈旧 kline 算错）。
    """
    now = _dt.now(BEIJING_TZ)
    today_bj = now.date()
    now_time = now.time()  # naive time（北京时区内 naive 比较足够，不跨时区）
    is_today_trading = is_trading_day(today_bj)

    # 1. stage 判定（S093 R1：pre_open 新增 + intraday 延到 15:30 + post_transition 从 15:30）
    #    非交易日保持盘后就绪态，不显示空状态——用户仍可复盘/看简报/看选股
    if not is_today_trading:
        stage = "post_market"  # 非交易日 = 上一交易日盘后就绪态
    elif now_time < _time(9, 0):
        stage = "pre_market"  # 17:15→09:00 跨夜就绪（今日盘后=次日盘前）
    elif now_time < _time(9, 30):
        stage = "pre_open"  # 09:00-09:30 集合竞价/开盘准备（S093 新增）
    elif now_time < _time(15, 30):
        stage = "intraday"  # 09:30-15:30 盘中交易（最新交易规则延迟到 15:30）
    elif now_time < _time(17, 15):
        stage = "post_transition"  # 15:30-17:15 数据采集渐进
    else:
        stage = "post_market"  # 17:15→ 跨夜就绪（= 次日 pre_market）

    # R8a：过渡窗内手动选"今天"(== today_bj 且交易日) → 复用自动态
    # （选今天等于没选；防前瞻拿到 T+1 用陈旧 kline 算错）
    if date_override is not None and date_override == today_bj and is_today_trading:
        date_override = None
    is_manual = date_override is not None

    # 2. F 推进逻辑（17:15 时间驱动，不因 cron 失败阻塞——M4 闭合）
    if is_manual:
        F = date_override  # type: ignore[assignment]
    elif is_today_trading and now_time >= _time(17, 15):
        F = last_trading_date(today_bj)  # 今日交易日 = T
    else:
        F = prev_trading_date(today_bj)  # 上一交易日 = T-1

    # 3. review 独立推进（15:30 收盘后立即推进到 T，已有实时数据先看）
    if is_manual:
        review_advanced = False  # 手动模式定时器不推进
        review = F
    elif is_today_trading and now_time >= _time(15, 30):
        review_advanced = True
        review = last_trading_date(today_bj)  # 今日交易日 = T
    else:
        review_advanced = False
        review = F

    # 4. today（当日数据日）—— R3 表格 + R4：盘后/非交易日当日=F 简报快照
    if is_manual:
        today = F  # 当日=F 简报快照
    elif is_today_trading and stage in ("pre_market", "pre_open", "intraday"):
        today = next_trading_date(F)  # F 的下一交易日 = T（今早简报/实时盯盘）
    else:
        today = F  # 盘后/非交易日：简报快照（R4 降级）

    # 5. forward（前瞻数据日）= F 的下一交易日（周五→周一，非日历 +1）
    forward = next_trading_date(F)

    # 6. next_*_at：下次 15:30 / 17:15 推进的 epoch 时间戳（秒）
    #    前端用 next_*_at - Date.now() 算 setTimeout，零本地时区判断（R14）
    def _next_advance_epoch(target_hour: int, target_minute: int) -> float:
        target_t = _time(target_hour, target_minute)
        if is_today_trading and now_time < target_t:
            d = today_bj  # 今日该时刻
        else:
            d = next_trading_date(today_bj)  # 下一交易日该时刻
        return _dt.combine(d, target_t, tzinfo=BEIJING_TZ).timestamp()

    next_review_advance_at = _next_advance_epoch(15, 30)
    next_f_advance_at = _next_advance_epoch(17, 15)

    return {
        "F": F.isoformat(),
        "review": review.isoformat(),
        "today": today.isoformat(),
        "forward": forward.isoformat(),
        "stage": stage,
        "is_trading_day": is_today_trading,
        "review_advanced": review_advanced,
        "server_now": now.isoformat(),
        "next_review_advance_at": next_review_advance_at,
        "next_f_advance_at": next_f_advance_at,
        "non_trading": not is_today_trading,  # 非交易日 → 定时器不推进（stage 保持 post_market 就绪态）
    }
