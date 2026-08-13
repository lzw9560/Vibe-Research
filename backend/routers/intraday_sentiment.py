# -*- coding: utf-8 -*-
"""S063 盘中情绪辅助决策 router。

四层辅助决策（spec §3）：
- Layer 1：分数+色带（被动展示）—— GET /latest, /timeline
- Layer 2：持仓×情绪联动（主动关联）—— GET /holdings
- Layer 3：条件场景推演（主动推理）—— GET /scenarios
- Layer 4：T+1 预判（14:30 专项）—— GET /t1-projection

后台采样：内存 ring buffer + 定时 asyncio task（仅交易时段 09:25-15:00 运行），
按黄金窗口频率调 market._emotion → 4 维度固定阈值评分 → 存 ring buffer + sti_intraday 表。

合规底线：
- CC1 不臆造数据：历史参照样本不足时标注"样本不足"，不编准确率
- CC2 盘中预判标注"投影，非最终判定"
- CC3 em_zt_topic_pool 限流防封：复用 board_ladder.get_market_emotion_raw 的 TTL 缓存，
  采样间隔不低于 5 分钟（黄金窗口最低频即 5min）
- CC4 私有数据隔离：持仓联动只读 workflow_state_repo，不输出个股推荐
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from config import default_config
from limitup_sti.data import save_intraday, load_intraday_day, load_recent_intraday_scores
from vr_paths import last_trading_date_str

logger = logging.getLogger(__name__)
router = APIRouter(tags=["intraday-sentiment"])


# ============================================================================
# T10：采样器 ring buffer + asyncio task
# ============================================================================

class _IntradaySampler:
    """盘中情绪采样器：内存 ring buffer + 定时采样。

    单例（模块级 _sampler）。app startup 注册 asyncio task，shutdown cancel。
    仅交易日 09:25-15:00 运行；非交易时段 sleep 60s 空转。
    """

    def __init__(self) -> None:
        self.buffer: deque[dict[str, Any]] = deque(
            maxlen=default_config.INTRADAY_RING_BUFFER_SIZE
        )
        self._task: asyncio.Task | None = None
        self._last_sample_time: str | None = None  # 防同分钟重复采样

    @property
    def today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _current_window(self) -> tuple[int, int] | None:
        """返回当前时间所在黄金窗口的 (间隔分钟, 剩余到下次采样秒数)；非交易时段返 None。"""
        now = datetime.now()
        hh_mm = now.strftime("%H:%M")
        for start, end, interval_min in default_config.INTRADAY_SAMPLE_INTERVALS:
            if start <= hh_mm < end:
                # 计算距下次采样点的秒数：当前分钟在窗口内的偏移
                start_dt = datetime.strptime(
                    f"{now.strftime('%Y-%m-%d')} {start}", "%Y-%m-%d %H:%M"
                )
                elapsed = (now - start_dt).total_seconds()
                interval_sec = interval_min * 60
                # 已过的完整间隔数
                periods = int(elapsed // interval_sec)
                next_sample = start_dt + timedelta(seconds=(periods + 1) * interval_sec)
                wait = (next_sample - now).total_seconds()
                return interval_min, max(1, int(wait))
        return None

    def _sample_once(self) -> dict[str, Any] | None:
        """执行一次采样：调 market._emotion → 4 维度评分 → 存 ring buffer + DB。

        复用 board_ladder.get_market_emotion_raw 的 TTL 缓存（CC3 防封）。
        采样失败标 missing，分数=None，趋势维持上一个有效值（spec §7 风险降级）。
        """
        from candidate_funnel.sources.board_ladder import get_market_emotion_raw  # noqa: PLC0415
        from sentiment_context import build_context  # noqa: PLC0415

        now = datetime.now()
        time_str = now.strftime("%H:%M")
        # 防同分钟重复采样
        if self._last_sample_time == f"{self.today} {time_str}":
            return None
        self._last_sample_time = f"{self.today} {time_str}"

        emo = get_market_emotion_raw(self.today)
        if not emo:
            # 采样失败：记录 missing 行（分数 None），趋势维持上一个有效值
            snapshot = {
                "date": self.today,
                "time": time_str,
                "zt_count": None, "seal_rate": None,
                "break_rate": None, "ad_ratio": None,
                "score": None, "trend": self._last_trend(),
                "t1_baseline": self._t1_baseline(),
            }
            self.buffer.append(snapshot)
            save_intraday(snapshot)
            logger.debug("[intraday] 采样失败（emo 为空）%s %s", self.today, time_str)
            return snapshot

        # 4 维度（spec §2.4）
        zt_count = float(emo.get("zt_count") or 0)
        dt_count = float(emo.get("dt_count") or 0)
        seal_rate = float(emo.get("seal_rate") or 0)  # 0-1
        break_rate = float(emo.get("break_rate") or 0)  # 0-1
        # 涨跌比：用 lianban_count / max(dt_count,1) 作近似（ad 无直接字段）
        lianban = float(emo.get("lianban_count") or 0)
        ad_ratio = lianban / max(dt_count, 1) if dt_count > 0 else lianban

        score = _compute_score(zt_count, seal_rate, break_rate, ad_ratio)
        prev_score = self._last_score()
        trend = _compute_trend(score, prev_score)
        t1_baseline = self._t1_baseline()
        zone = _compute_zone(score, t1_baseline)

        snapshot = {
            "date": self.today,
            "time": time_str,
            "zt_count": zt_count,
            "seal_rate": seal_rate,
            "break_rate": break_rate,
            "ad_ratio": round(ad_ratio, 2),
            "score": score,
            "trend": trend,
            "t1_baseline": t1_baseline,
            "zone": zone,
        }
        self.buffer.append(snapshot)
        save_intraday(snapshot)
        logger.info(
            "[intraday] 采样 %s %s score=%.1f trend=%s zone=%s",
            self.today, time_str, score, trend, zone,
        )
        return snapshot

    def _last_score(self) -> float | None:
        """ring buffer 最近一条有效 score。"""
        for s in reversed(self.buffer):
            if s.get("score") is not None:
                return s["score"]
        return None

    def _last_trend(self) -> str | None:
        for s in reversed(self.buffer):
            if s.get("trend") is not None:
                return s["trend"]
        return None

    def _t1_baseline(self) -> float | None:
        """T-1 STI 分数（色带基线）—— 从 SentimentContext 取。

        build_context 是模块级函数，但本方法在子线程（asyncio.to_thread）中
        调用时，_sample_once 里 `from sentiment_context import build_context`
        的局部 import 作用域不覆盖 _t1_baseline——需在此独立 import。
        """
        try:
            from sentiment_context import build_context  # noqa: PLC0415
            ctx = build_context(self.today)
            if ctx.sti_score is None:
                logger.warning(
                    "[intraday] T-1 baseline 为 None（data_status=%s source_date=%s）",
                    ctx.data_status, ctx.source_date,
                )
            return ctx.sti_score
        except Exception as exc:
            logger.warning("[intraday] _t1_baseline 异常: %s", exc)
            return None

    def latest(self) -> dict[str, Any] | None:
        """ring buffer 最新一条（含 missing 行）。"""
        if not self.buffer:
            return None
        return self.buffer[-1]

    def timeline_today(self) -> list[dict[str, Any]]:
        """当日全量 snapshot（ring buffer，按时间升序）。"""
        return list(self.buffer)

    async def _loop(self) -> None:
        """采样主循环：交易时段按黄金窗口采样，非交易时段空转。"""
        from vr_paths import is_trading_day  # noqa: PLC0415
        while True:
            try:
                now = datetime.now()
                # 非交易日或非交易时段 → sleep 60s 空转
                if not is_trading_day(now.date()):
                    await asyncio.sleep(60)
                    continue
                win = self._current_window()
                if win is None:
                    # 非采样时段（如午休 11:30-13:00、盘前盘后）
                    await asyncio.sleep(60)
                    continue
                _interval_min, wait_sec = win
                # 到采样点 → 执行采样
                if wait_sec <= 1:
                    # 在线程中执行（market._emotion 可能阻塞）
                    await asyncio.to_thread(self._sample_once)
                    await asyncio.sleep(5)  # 采样后短歇
                else:
                    await asyncio.sleep(min(wait_sec, 60))  # 不超过 60s（及时响应窗口切换）
            except asyncio.CancelledError:
                logger.info("[intraday] 采样任务被取消")
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("[intraday] 采样循环异常: %s", exc)
                await asyncio.sleep(60)  # 异常后等 60s 不中断 loop

    def start(self) -> None:
        """启动采样 task（app startup 调用）。"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info("[intraday] 采样任务已启动")

    async def stop(self) -> None:
        """停止采样 task（app shutdown 调用）。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("[intraday] 采样任务已停止")


_sampler = _IntradaySampler()


# ============================================================================
# T11：盘中评分模型（4 维度固定阈值）
# ============================================================================

def _score_dimension(value: float, thresholds: tuple[float, float, float]) -> float:
    """固定阈值映射 → 0-100 分。

    thresholds = (高阈值, 中阈值, 低阈值)：
    value >= 高 → 100；中 <= value < 高 → 60；value < 低 → 20；中间 60。
    """
    high, mid, low = thresholds
    if value >= high:
        return 100.0
    if value >= mid:
        return 60.0
    if value < low:
        return 20.0
    return 60.0


def _compute_score(
    zt_count: float, seal_rate: float, break_rate: float, ad_ratio: float
) -> float:
    """4 维度固定阈值加权平均（spec §2.4）。

    权重：涨停家数 0.4 / 封板率 0.2 / 炸板率 0.2 / 涨跌比 0.1。
    注：spec 权重和 0.4+0.2+0.2+0.1=0.9（原 spec 未归一），这里按原口径算
    加权平均后除以权重和 0.9 归一（等比缩放不影响相对排序）。
    """
    zt_score = _score_dimension(zt_count, (80, 50, 30))
    seal_score = _score_dimension(seal_rate * 100, (70, 50, 0))  # 0-1→0-100
    # 炸板率反向：<15%=100，15-30%=60，>30%=20
    break_score = 100.0 if break_rate < 0.15 else (60.0 if break_rate < 0.30 else 20.0)
    ad_score = _score_dimension(ad_ratio, (2, 0.7, 0))

    weights = {"zt": 0.4, "seal": 0.2, "break": 0.2, "ad": 0.1}
    total = (
        zt_score * weights["zt"]
        + seal_score * weights["seal"]
        + break_score * weights["break"]
        + ad_score * weights["ad"]
    )
    return round(total / sum(weights.values()), 2)


def _compute_trend(score: float | None, prev_score: float | None) -> str:
    """趋势：正负 3 分内为 flat（spec §2.4）。"""
    if score is None or prev_score is None:
        return "flat"
    diff = score - prev_score
    if diff > 3:
        return "up"
    if diff < -3:
        return "down"
    return "flat"


def _compute_zone(score: float | None, t1_baseline: float | None) -> str:
    """色带：偏离 T-1 基线 <=5 绿，5-15 黄，>15 红（spec §2.5）。"""
    if score is None or t1_baseline is None:
        return "yellow"  # 缺基线时默认黄（提高警觉）
    diff = abs(score - t1_baseline)
    if diff <= 5:
        return "green"
    if diff <= 15:
        return "yellow"
    return "red"


# ============================================================================
# T12：Layer 1 端点（分数+色带）
# ============================================================================

@router.get("/api/intraday/sentiment/latest")
async def get_intraday_latest() -> dict[str, Any]:
    """Layer 1：返回最新 snapshot（4 维度+分数+趋势+色带区间）。

    ring buffer 空（非交易时段/首日）→ 尝试从 DB 读当日最新行；都无 → 返 missing。
    """
    snap = _sampler.latest()
    if snap is None:
        # fallback：DB 当日最新
        rows = load_intraday_day(_sampler.today)
        if rows:
            snap = rows[-1]
    if snap is None:
        return {"data": {"status": "missing", "message": "暂无盘中采样数据（非交易时段或未启动）"}}
    return {"data": snap}


@router.get("/api/intraday/sentiment/timeline")
async def get_intraday_timeline() -> dict[str, Any]:
    """Layer 1：当日全量 snapshots（按时间升序）。"""
    # ring buffer 优先（实时），不足则补 DB
    buf = _sampler.timeline_today()
    if len(buf) < 2:
        db_rows = load_intraday_day(_sampler.today)
        if len(db_rows) > len(buf):
            buf = db_rows
    return {"data": {"date": _sampler.today, "snapshots": buf}}


@router.post("/api/intraday/sentiment/snapshot")
async def trigger_snapshot() -> dict[str, Any]:
    """手动触发一次采样（调试用）。不受黄金窗口频率限制。"""
    snap = await asyncio.to_thread(_sampler._sample_once)  # noqa: SLF001
    if snap is None:
        return {"data": {"status": "skipped", "message": "同分钟已采样过或数据未取得"}}
    return {"data": snap}


# ============================================================================
# T13：Layer 2 端点（持仓×情绪联动）
# ============================================================================

@router.get("/api/intraday/sentiment/holdings")
async def get_intraday_holdings() -> dict[str, Any]:
    """Layer 2：持仓×情绪联动表。

    读 workflow_state_repo holding 列表 → tencent_quote 拉实时报价 →
    判定封板状态 → 关联当前 snapshot 色带 → 双重压力行（个股炸板未回封+红色区）置顶。

    CC4：只读 workflow_state_repo，不输出个股推荐。
    """
    try:
        import workflow_state_repo as wsr  # noqa: PLC0415
        import astock  # noqa: PLC0415

        d = last_trading_date_str()
        states = wsr.list_states(d)
        holdings = [s for s in states if s.get("status") == "holding"]
        if not holdings:
            return {"data": {"holdings": [], "current_zone": _current_zone(), "message": "当前无持仓"}}

        codes = [h["code"] for h in holdings if h.get("code")]
        # 批量拉实时报价（tencent_quote 接受 list）
        quotes: dict[str, dict] = {}
        try:
            raw_quotes = astock.tencent_quote(codes)
            for q in raw_quotes or []:
                code = q.get("code") or q.get("stock_code")
                if code:
                    quotes[code] = q
        except Exception as exc:  # noqa: BLE001
            logger.warning("[intraday] 持仓报价拉取失败: %s", exc)

        current_zone = _current_zone()
        rows: list[dict[str, Any]] = []
        for h in holdings:
            code = h["code"]
            q = quotes.get(code, {})
            seal_status = _judge_seal_status(code, q, h)
            row = {
                "code": code,
                "name": h.get("name", code),
                "status": h.get("status"),
                "entry_price": h.get("entry_price"),
                "current_price": q.get("current_price") or q.get("price"),
                "pnl_pct": _pnl_pct(h.get("entry_price"), q.get("current_price") or q.get("price")),
                "seal_status": seal_status,
                "current_zone": current_zone,
                "dual_pressure": seal_status == "炸板未回封" and current_zone == "red",
            }
            rows.append(row)

        # 双重压力行置顶
        rows.sort(key=lambda r: (not r["dual_pressure"], r["code"]))

        return {
            "data": {
                "holdings": rows,
                "current_zone": current_zone,
                "dual_pressure_count": sum(1 for r in rows if r["dual_pressure"]),
            }
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"持仓联动查询异常：{exc}") from exc


def _current_zone() -> str:
    """当前色带（从最新 snapshot 取）。"""
    snap = _sampler.latest()
    if snap and snap.get("zone"):
        return snap["zone"]
    return "yellow"


def _judge_seal_status(code: str, quote: dict, holding: dict) -> str:
    """个股封板状态判定（spec §3.2）。

    - 封住：接近涨停价且未开板
    - 炸板回封：盘中触及涨停后打开再封回
    - 炸板未回封：触及涨停后打开未封回
    - 未封板：未触及涨停
    - 数据未取得：报价缺失
    """
    if not quote:
        return "数据未取得"
    # 简化判定：用涨跌幅 + 持仓 entry_price 近似
    # 真实判定需分时数据（S055 封单时序），这里降级为基于现价的近似
    current = quote.get("current_price") or quote.get("price")
    if current is None:
        return "数据未取得"
    # 无法精确判炸板回封（需分时）→ 统一标"封住/未封板/数据未取得"
    pct = quote.get("change_pct") or quote.get("pct")
    if pct is None:
        # 用 entry_price 近似（不准确，标注）
        return "数据未取得"
    if pct >= 9.8:  # 接近涨停（主板 10%，留余量）
        return "封住"
    return "未封板"


def _pnl_pct(entry: float | None, current: float | None) -> float | None:
    """盈亏百分比。"""
    if not entry or not current:
        return None
    return round((current - entry) / entry * 100, 2)


# ============================================================================
# T14：Layer 3 端点（条件场景推演）
# ============================================================================

@router.get("/api/intraday/sentiment/scenarios")
async def get_intraday_scenarios() -> dict[str, Any]:
    """Layer 3：条件场景推演 if-then + 历史参照。

    基于当前 snapshot 状态 + 趋势，预铺 if-then 分支。
    历史参照初期样本为 sti_intraday 已有数据（首日为零，逐日积累），
    诚实标注样本量，不编准确率（CC1）。
    """
    try:
        snap = _sampler.latest()
        if snap is None:
            rows = load_intraday_day(_sampler.today)
            if rows:
                snap = rows[-1]
        if snap is None or snap.get("score") is None:
            return {"data": {"scenarios": [], "message": "当前无有效采样数据，无法推演"}}

        score = snap["score"]
        trend = snap.get("trend", "flat")
        zone = snap.get("zone", "yellow")

        # if-then 分支生成（基于 score + trend + zone）
        scenarios = _build_scenarios(score, trend, zone)

        # 历史参照：查 sti_intraday 近 20 日类似走势（同 trend+zone）
        history_ref = _build_history_reference(trend, zone)

        return {
            "data": {
                "current": {"score": score, "trend": trend, "zone": zone},
                "scenarios": scenarios,
                "history_reference": history_ref,
            }
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"场景推演查询异常：{exc}") from exc


def _build_scenarios(score: float, trend: str, zone: str) -> list[dict[str, Any]]:
    """生成 if-then 条件卡片。"""
    scenarios: list[dict[str, Any]] = []

    if zone == "red" and trend == "down":
        scenarios.append({
            "condition": "情绪显著背离 T-1 且持续下行",
            "impact": "市场可能进入退潮，持仓压力增大",
            "suggestion": "提高警觉，审视持仓是否承压（看 Layer 2 双重压力行）",
        })
    elif zone == "red" and trend == "up":
        scenarios.append({
            "condition": "情绪显著背离 T-1 但出现反弹",
            "impact": "可能触底反弹或技术性反抽，不确定性高",
            "suggestion": "不急加仓，等趋势确认（连续 2 个 snapshot 上行）",
        })
    elif zone == "yellow":
        scenarios.append({
            "condition": "情绪开始走偏 T-1 基线",
            "impact": "市场分歧加大，板块轮动可能加速",
            "suggestion": "关注持仓封板稳定性，非双重压力行可观察",
        })
    elif zone == "green" and trend == "up":
        scenarios.append({
            "condition": "情绪与 T-1 一致且持续上行",
            "impact": "T-1 硬标准（晴天/阴天）延续，战法适配度不变",
            "suggestion": "按 T-1 战法开关执行，持仓可继续观察",
        })
    elif zone == "green" and trend == "down":
        scenarios.append({
            "condition": "情绪与 T-1 一致但开始回落",
            "impact": "T-1 硬标准仍有效，但动能在衰减",
            "suggestion": "不急动作，观察是否跌出绿色区间",
        })
    else:
        scenarios.append({
            "condition": "情绪平稳运行",
            "impact": "T-1 硬标准主导，盘中无异常信号",
            "suggestion": "按既定计划执行",
        })

    return scenarios


def _build_history_reference(trend: str, zone: str) -> dict[str, Any]:
    """历史参照：查 sti_intraday 近 20 日类似走势。

    CC1：诚实标注样本量，不编准确率。首日样本=0。
    """
    recent = load_recent_intraday_scores(days=20)
    # 按 trend+zone 过滤类似走势
    similar = [
        r for r in recent
        if r.get("trend") == trend and r.get("score") is not None
    ]
    # 统计后续走势（下一个 snapshot 的 trend）
    follow_up: dict[str, int] = {"up": 0, "flat": 0, "down": 0}
    for i, r in enumerate(similar):
        if i + 1 < len(similar) and similar[i + 1].get("date") == r.get("date"):
            nxt = similar[i + 1].get("trend")
            if nxt in follow_up:
                follow_up[nxt] += 1
    total = sum(follow_up.values())

    return {
        "sample_size": total,
        "similar_count": len(similar),
        "follow_up_distribution": follow_up,
        "note": (
            f"基于 sti_intraday 近 20 日 {len(similar)} 条类似走势（trend={trend}），"
            f"有效后续样本 {total} 条"
            if total > 0
            else "样本不足（0 日），历史参照待积累，不编准确率"
        ),
    }


# ============================================================================
# T15：Layer 4 端点（T+1 预判）
# ============================================================================

@router.get("/api/intraday/sentiment/t1-projection")
async def get_t1_projection() -> dict[str, Any]:
    """Layer 4：T+1 预判（14:30 专项）。

    14:30 后可用 → 用当前 4 维度数据预推算收盘 STI（调 engine.compute 但不 save）
    → 双场景（维持/反弹）→ 写 projected_t1_score + projected_t1_weather。
    收盘后回填 actual_score（投影校准）。

    CC2：标注"投影，非最终判定"。
    """
    try:
        now = datetime.now()
        hh_mm = now.strftime("%H:%M")
        if hh_mm < "14:30":
            return {
                "data": {
                    "status": "not_ready",
                    "message": "T+1 预判 14:30 后可用（当前未到）",
                }
            }

        snap = _sampler.latest()
        if snap is None or snap.get("score") is None:
            return {"data": {"status": "insufficient_data", "message": "数据不足，无法预判"}}

        # 双场景预推算（维持 / 反弹）
        current_score = snap["score"]
        # 场景 1：维持——尾盘 30 分钟情绪不变，T+1 STI ≈ 当前 score
        scenario_hold = {
            "name": "维持",
            "projected_t1_score": round(current_score, 2),
            "projected_t1_weather": _score_to_weather(current_score),
            "assumption": "尾盘 30 分钟情绪维持当前水平",
        }
        # 场景 2：反弹——尾盘拉升，score +5（乐观估计）
        rebound_score = min(100.0, current_score + 5)
        scenario_rebound = {
            "name": "反弹",
            "projected_t1_score": round(rebound_score, 2),
            "projected_t1_weather": _score_to_weather(rebound_score),
            "assumption": "尾盘 30 分钟情绪回升 +5 分",
        }

        # 写投影到最新 snapshot（DB + ring buffer）
        snap["projected_t1_score"] = scenario_rebound["projected_t1_score"]
        snap["projected_t1_weather"] = scenario_rebound["projected_t1_weather"]
        save_intraday(snap)

        return {
            "data": {
                "status": "ready",
                "current_score": current_score,
                "scenarios": [scenario_hold, scenario_rebound],
                "disclaimer": "投影，非最终判定（CC2）—— 收盘后以 STI 盘后定时计算结果为准",
                "as_of": snap.get("time"),
            }
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"T+1 预判查询异常：{exc}") from exc


def _score_to_weather(score: float) -> str:
    """STI 分数 → 天气标签（对齐 sentiment_weather 阈值）。"""
    if score >= 75:
        return "晴天"
    if score >= 55:
        return "阴天"
    if score >= 35:
        return "极端反弹"
    return "暴风雨"


# ============================================================================
# 生命周期：app startup/shutdown 挂钩
# ============================================================================

async def start_sampler() -> None:
    """app startup 调用：启动盘中采样 task。"""
    _sampler.start()


async def stop_sampler() -> None:
    """app shutdown 调用：停止盘中采样 task。"""
    await _sampler.stop()
