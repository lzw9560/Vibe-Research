# -*- coding: utf-8 -*-
"""S066 Phase 0e 前向测试（paper trading）框架——spec §13.0 上线路径最后验证关。

spec §13.0/§0e：
- 用 0d 权重跑系统：涨停股 × 策略分排序 × 板块周期 × 日历因子
- 每日记录推荐 vs 实际表现
- 通过标准（§44 60日复验窗口，forward_test 内部 passed 判定逻辑不变）：系统无崩溃 + 推荐胜率 >= §13.0 绝对 60% + lift>=2x
- 不通过 → 修 bug 再跑 20 天
- 前向测试期间不投真金

§44 60日复验窗口口径（spec §13 ①，诚实标注非阻断）：
- 随机基准 = 新表 universe_returns（同信号日全体涨停股次日 winrate = 零选股基准率）。
- forward_test_records（picks，code×strategy 多行）不动；strategy winrate 从此表、random winrate 从 universe_returns。
- run_daily_forward_test 主动记录 universe codes（收益 NULL，次日回填）→ lift 不可被调用方伪造。
- gate（forward_test 内部 passed 判定，逻辑不变）：winrate>=60（§13.0 绝对）AND lift>=2.0（§44）AND random_settled>0 AND consecutive_loss<8。
- **60日复验窗口口径注**：passed=False 不阻断接入跑通——§44 统计结论（lift<2x）作为诚实标注（标"未 validated/探索性"），系统仍按等权 placeholder 推进；60 日数据积累后复验，破2x→validated 升级权重，<2x→保留接入标注"复验未破2x"。

每日盘后调用 record_daily_recommendations → 次日 record_actual_returns（picks）+ record_universe_returns（universe）回填。
诚实边界：无 next_bar 收益的标 missing，不臆造；无 universe_returns → passed=False + note（不能伪造 lift）。
"""
from __future__ import annotations

import sqlite3
import logging
from dataclasses import dataclass

from config import GENE_SCORES_DB_PATH
from vr_paths import resolve_data_dir

_DB = GENE_SCORES_DB_PATH

# §44 / §13.0 通过门槛（绝对，非 benchmark×0.8 弱 degradation）
# 注：forward_test 内部 passed 判定逻辑不变；60日复验窗口口径下 passed=False 不阻断接入跑通。
PASS_WINRATE_FLOOR: float = 60.0   # §13.0：alpha>60% 才加复杂度
PASS_LIFT_FLOOR: float = 2.0       # §44 60日复验窗口：lift<2 标未 validated（前向测试仍跑，60日后复验定权重）
PASS_LIFT_HARD_FLOOR: float = 1.0  # §44 硬底线：lift<1 劣于随机 → 移除/权重0，不保留跑通


# ===========================================================================
# 表结构（幂等迁移）
# ===========================================================================

_FORWARD_TEST_SQL = """
CREATE TABLE IF NOT EXISTS forward_test_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,              -- 信号日（推荐日）
    code TEXT NOT NULL,                     -- 推荐股票代码
    name TEXT,                              -- 股票名称
    strategy_code TEXT NOT NULL,            -- 战法 code
    strategy_score REAL,                    -- 策略分
    weather_state TEXT,                     -- 当日天气
    position_multiplier REAL,               -- 日历因子仓位乘数
    recommended_position REAL,              -- 建议仓位 %
    return_open2close REAL,                -- 次日开盘到收盘收益 %
    return_close2close REAL,               -- 收盘到收盘收益 %
    next_pctChg REAL,                       -- 次日涨跌幅 %
    is_win INTEGER DEFAULT 0,                    -- 是否盈利（return_open2close > 0）
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, code, strategy_code)
);
CREATE INDEX IF NOT EXISTS idx_forward_test_date ON forward_test_records(signal_date);
CREATE INDEX IF NOT EXISTS idx_forward_test_code ON forward_test_records(code);

-- §44 随机基准源：同信号日全体涨停股次日收益（零选股基准率）。
-- 每 code 一行（UNIQUE signal_date,code）；收益由 record_universe_returns 次日回填。
CREATE TABLE IF NOT EXISTS universe_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,              -- 信号日
    code TEXT NOT NULL,                     -- 涨停股代码
    return_open2close REAL,                -- 次日 open2close %
    return_close2close REAL,               -- 收盘到收盘 %
    next_pctChg REAL,                       -- 次日涨跌幅 %
    is_win INTEGER DEFAULT 0,              -- return_open2close > 0
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, code)
);
CREATE INDEX IF NOT EXISTS idx_universe_returns_date ON universe_returns(signal_date);
"""


def _ensure_table() -> None:
    """幂等建表（import 时调用一次）。"""
    try:
        conn = sqlite3.connect(_DB, timeout=10)
        conn.executescript(_FORWARD_TEST_SQL)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI（分数 [lo, hi]，0-1）。n=0 返 (0,0)。"""
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return c - h, c + h


# ===========================================================================
# 数据结构
# ===========================================================================

@dataclass(frozen=True)
class DailyRecommendation:
    """单条每日推荐记录。"""
    signal_date: str
    code: str
    name: str
    strategy_code: str
    strategy_score: float
    weather_state: str | None = None
    position_multiplier: float = 1.0
    recommended_position: float = 0.0


@dataclass(frozen=True)
class ForwardTestResult:
    """前向测试汇总结果（§44 60日复验窗口：含随机基准 + lift + Wilson CI，诚实标注非阻断）。"""
    total_days: int
    total_recommendations: int
    settled_count: int            # picks 有 next_bar 收益的记录数
    win_count: int               # picks wins
    win_rate: float               # picks 胜率 0-100
    avg_return: float             # picks 平均 open2close %
    # §44 随机基准 + lift（60日复验窗口：作为诚实标注，非接入阻断）
    random_settled: int = 0        # universe 有收益的记录数
    random_win_count: int = 0
    random_baseline_win_rate: float = 0.0  # universe winrate %（零选股基准率）
    lift: float = 0.0             # strategy / random（<2x 标未 validated，不阻断接入跑通，60日后复验）
    strategy_ci: tuple[float, float] = (0.0, 0.0)   # Wilson [lo,hi] %
    random_ci: tuple[float, float] = (0.0, 0.0)
    is_exploratory: bool = False  # §44(2)：n<30 探索性非定论
    universe_coverage: tuple[int, int] = (0, 0)  # (已回填收益, 已记录 codes)
    benchmark_win_rate: float = 0.0     # Phase 0b benchmark_A（信息字段，非门）
    pass_threshold: float = PASS_WINRATE_FLOOR  # §13.0 绝对 60（非 benchmark×0.8）
    passed: bool = False
    consecutive_loss: int = 0
    note: str = ""
    validation_status: str = "未 validated"  # §44 60日复验窗口三态：validated | 未 validated | 探索性


# ===========================================================================
# 写入：每日推荐（信号日）
# ===========================================================================

def record_daily_recommendations(
    signal_date: str,
    recommendations: list[DailyRecommendation],
) -> int:
    """记录某信号日的全部推荐（UPSERT 幂等）。

    信号日盘后调用：跑策略系统 → 记录推荐代码/策略分/天气/仓位。
    返回写入条数。
    """
    _ensure_table()
    if not recommendations:
        return 0
    conn = sqlite3.connect(_DB, timeout=10)
    inserted = 0
    try:
        for rec in recommendations:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO forward_test_records
                    (signal_date, code, name, strategy_code, strategy_score,
                     weather_state, position_multiplier, recommended_position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rec.signal_date, rec.code, rec.name, rec.strategy_code,
                     rec.strategy_score, rec.weather_state, rec.position_multiplier,
                     rec.recommended_position),
                )
                inserted += 1
            except Exception:
                continue
        conn.commit()
    finally:
        conn.close()
    return inserted


# ===========================================================================
# 回填：次日实际收益（T+1 盘后）
# ===========================================================================

def record_actual_returns(
    signal_date: str,
    returns_data: dict[str, dict[str, float | None]],
) -> int:
    """回填某信号日 picks 的次日实际收益（forward_test_records）。

    signal_date: 信号日（推荐日），不是次日
    returns_data: {code: {return_open2close, return_close2close, next_pctChg}}

    次日盘后调用：拉 kline → 算次日收益 → 回填 picks。
    缺 next_bar 的标 None（不臆造）。
    返回更新条数。
    """
    _ensure_table()
    if not returns_data:
        return 0
    conn = sqlite3.connect(_DB, timeout=10)
    updated = 0
    try:
        for code, returns in returns_data.items():
            o2c = returns.get("return_open2close")
            c2c = returns.get("return_close2close")
            pct = returns.get("next_pctChg")
            is_win = 1 if (o2c is not None and o2c > 0) else 0
            try:
                cur = conn.execute(
                    """UPDATE forward_test_records
                    SET return_open2close = ?, return_close2close = ?,
                        next_pctChg = ?, is_win = ?
                    WHERE signal_date = ? AND code = ?""",
                    (o2c, c2c, pct, is_win, signal_date, code),
                )
                if cur.rowcount > 0:
                    updated += 1
            except Exception:
                continue
        conn.commit()
    finally:
        conn.close()
    return updated


def record_universe_returns(
    signal_date: str,
    returns_data: dict[str, dict[str, float | None]],
) -> int:
    """回填某信号日 universe（全体涨停股）的次日收益（universe_returns 表）。

    universe = 同信号日全体涨停股（零选股基准率），§44 随机基准源（60日复验窗口：诚实标注，非接入阻断）。
    与 record_actual_returns（picks）独立：picks→forward_test_records，universe→universe_returns。
    幂等（UNIQUE(signal_date,code)，INSERT OR REPLACE）。
    缺 next_bar 的标 None（不臆造）。返回 upsert 条数。
    """
    _ensure_table()
    if not returns_data:
        return 0
    conn = sqlite3.connect(_DB, timeout=10)
    upserted = 0
    try:
        for code, returns in returns_data.items():
            o2c = returns.get("return_open2close")
            c2c = returns.get("return_close2close")
            pct = returns.get("next_pctChg")
            is_win = 1 if (o2c is not None and o2c > 0) else 0
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO universe_returns
                    (signal_date, code, return_open2close, return_close2close,
                     next_pctChg, is_win)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (signal_date, code, o2c, c2c, pct, is_win),
                )
                upserted += 1
            except Exception:
                continue
        conn.commit()
    finally:
        conn.close()
    return upserted


# ===========================================================================
# 汇总：前向测试结果（§44 60日复验窗口口径，forward_test 内部 passed 判定逻辑不变）
# ===========================================================================

def get_forward_test_summary(
    benchmark_win_rate: float = 60.0,  # Phase 0b benchmark_A（信息字段，非门）
    min_days: int = 20,
) -> ForwardTestResult:
    """汇总前向测试结果（§13.0 + §44 60日复验窗口，forward_test 内部 passed 判定逻辑不变）。

    §44 60日复验窗口口径（结论前必过的诚实门——诚实标注非阻断）：
    - total_days >= min_days（20 交易日）
    - strategy_win_rate >= PASS_WINRATE_FLOOR（§13.0 绝对 60%，非 benchmark×0.8 弱 bar）
    - lift = strategy_winrate / random_baseline_winrate >= PASS_LIFT_FLOOR（2.0；§44 60日复验窗口：lift<2 标未 validated，前向测试仍跑，60日后复验定权重）
    - random_settled > 0（universe_returns 有回填，否则无法算 lift → 不通过）
    - 无崩溃（consecutive_loss < 8，kill criteria 未触发）

    random_baseline = 同信号日全体涨停股次日 winrate（universe_returns）= 零选股基准率。
    无 universe_returns → passed=False + note（诚实：不能伪造 lift）。
    注：passed=False 不阻断接入跑通——§44 统计结论作为诚实标注（标"未 validated/探索性"），系统仍按等权 placeholder 推进；60 日数据积累后复验，破2x→validated 升级权重，<2x→保留接入标注"复验未破2x"。
    """
    _ensure_table()
    conn = sqlite3.connect(_DB, timeout=10)
    try:
        # —— 策略 picks（forward_test_records）——
        total = conn.execute("SELECT COUNT(*) FROM forward_test_records").fetchone()[0]
        s_settled = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE return_open2close IS NOT NULL"
        ).fetchone()[0]
        s_wins = conn.execute(
            "SELECT COUNT(*) FROM forward_test_records WHERE is_win = 1"
        ).fetchone()[0]
        days = conn.execute(
            "SELECT COUNT(DISTINCT signal_date) FROM forward_test_records"
        ).fetchone()[0]
        avg_row = conn.execute(
            "SELECT AVG(return_open2close) FROM forward_test_records WHERE return_open2close IS NOT NULL"
        ).fetchone()
        avg_return = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0
        recent = conn.execute(
            """SELECT is_win FROM forward_test_records
            WHERE return_open2close IS NOT NULL
            ORDER BY signal_date DESC, id DESC LIMIT 20"""
        ).fetchall()
        consecutive_loss = 0
        for r in recent:
            if r[0] == 0:
                consecutive_loss += 1
            else:
                break

        # —— 随机基准 universe（universe_returns）——
        u_total = conn.execute("SELECT COUNT(*) FROM universe_returns").fetchone()[0]
        u_settled = conn.execute(
            "SELECT COUNT(*) FROM universe_returns WHERE return_open2close IS NOT NULL"
        ).fetchone()[0]
        u_wins = conn.execute(
            "SELECT COUNT(*) FROM universe_returns WHERE is_win = 1"
        ).fetchone()[0]
    finally:
        conn.close()

    s_winrate = round(s_wins / s_settled * 100, 2) if s_settled > 0 else 0.0
    u_winrate = round(u_wins / u_settled * 100, 2) if u_settled > 0 else 0.0
    lift = round(s_winrate / u_winrate, 3) if u_winrate > 0 else 0.0
    s_lo, s_hi = _wilson(s_wins, s_settled)
    u_lo, u_hi = _wilson(u_wins, u_settled)
    is_exploratory = s_settled < 30  # §44(2)：n<30 探索性非定论（60日复验窗口：不阻断接入，标探索性跑通）

    # §44 60日复验窗口口径：forward_test 内部 passed 判定逻辑不变（lift>=2.0 仍为门）；
    # passed=False 不阻断接入跑通——§44 统计结论作为诚实标注，60 日后复验定权重。
    passed = (
        days >= min_days
        and s_settled > 0
        and s_winrate >= PASS_WINRATE_FLOOR
        and u_settled > 0
        and lift >= PASS_LIFT_FLOOR
        and consecutive_loss < 8
    )

    note_parts: list[str] = []
    if days < min_days:
        note_parts.append(f"样本不足：{days}/{min_days} 交易日")
    if s_settled == 0:
        note_parts.append("无已结算 picks（需次日回填收益）")
    elif total > 0 and s_settled < 0.8 * total:
        # 116 诚实层：picks 收益覆盖低（如 live 日 backtest_samples 未含收益）→ verdict 基于部分样本
        note_parts.append(f"picks 收益覆盖低（{s_settled}/{total} settled）→ verdict 基于部分样本（待 live 日收益回填）")
    if u_settled == 0:
        note_parts.append("无随机基准（universe_returns 未回填 → 无法 §44 验证 lift）")
    if u_settled > 0 and s_settled > 0:
        if lift < PASS_LIFT_HARD_FLOOR:
            note_parts.append(f"lift {lift}x < {PASS_LIFT_HARD_FLOOR}x → §44 硬底线（劣于随机，移除/权重0，不保留跑通）")
        elif lift < PASS_LIFT_FLOOR:
            note_parts.append(f"lift {lift}x < {PASS_LIFT_FLOOR}x → §44 噪声（未 validated，不阻断接入跑通，60日后复验）")
        if s_lo <= u_hi:  # 策略 CI 与随机 CI 重叠 = 不显著优于随机
            note_parts.append("策略 CI 与随机 CI 重叠（不显著优于随机）")
    if s_settled > 0 and s_winrate < PASS_WINRATE_FLOOR:
        note_parts.append(f"胜率 {s_winrate}% < §13.0 门槛 {PASS_WINRATE_FLOOR}%")
    if is_exploratory and s_settled > 0:
        note_parts.append(f"n={s_settled}<30 探索性（非定论）")
    if consecutive_loss >= 8:
        note_parts.append(f"连续亏损 {consecutive_loss} 笔（kill criteria 触发）")
    if not note_parts:
        note_parts.append("§44 前向测试通过（胜率>=60% + lift>=2x → validated）")

    # §44 60日复验窗口四态判定（语义层，基于 is_exploratory + lift + passed 派生）
    # - 探索性（n<30）：最高优先，数据不足非定论（即使 lift<1 也标探索性，样本不足无法定论）
    # - 劣于随机（lift<1）：硬底线，移除/权重0，不保留跑通
    # - validated（lift>=2 + winrate>=60 + ...）：通过 §44 门
    # - 未 validated（1<lift<2 或 winrate<60 等）：跑通中，60日后复验
    if is_exploratory:
        validation_status = "探索性"
    elif lift < PASS_LIFT_HARD_FLOOR:
        validation_status = "劣于随机"  # lift<1 硬底线：移除/权重0，不保留跑通
    elif passed:
        validation_status = "validated"
    else:
        validation_status = "未 validated"

    return ForwardTestResult(
        total_days=days,
        total_recommendations=total,
        settled_count=s_settled,
        win_count=s_wins,
        win_rate=s_winrate,
        avg_return=round(avg_return, 4),
        random_settled=u_settled,
        random_win_count=u_wins,
        random_baseline_win_rate=u_winrate,
        lift=lift,
        strategy_ci=(round(s_lo * 100, 2), round(s_hi * 100, 2)),
        random_ci=(round(u_lo * 100, 2), round(u_hi * 100, 2)),
        is_exploratory=is_exploratory,
        universe_coverage=(u_settled, u_total),
        benchmark_win_rate=benchmark_win_rate,
        pass_threshold=PASS_WINRATE_FLOOR,
        passed=passed,
        consecutive_loss=consecutive_loss,
        note="；".join(note_parts),
        validation_status=validation_status,
    )


# ===========================================================================
# 查询：单日推荐明细
# ===========================================================================

def get_daily_recommendations(signal_date: str) -> list[dict]:
    """取某信号日的全部推荐记录。"""
    _ensure_table()
    conn = sqlite3.connect(_DB, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM forward_test_records WHERE signal_date = ?
            ORDER BY strategy_score DESC""",
            (signal_date,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ===========================================================================
# 运行入口（盘后调度调用）
# ===========================================================================

def run_daily_forward_test(signal_date: str, weather_state: str | None = None) -> dict:
    """每日盘后前向测试入口。

    1. 跑策略系统（天气 → 策略组 → 策略分排序）→ 记录 picks
    2. 记录当日 universe codes（universe_returns，收益 NULL，次日 record_universe_returns 回填）
    3. 次日盘后回填收益（picks 由 record_actual_returns，universe 由 record_universe_returns）
    4. 返回当日推荐数

    §44 60日复验窗口：主动记录 universe codes 让框架持有"它看到的全体"，lift 不可被调用方伪造（诚实标注，非接入阻断）。
    """
    from limitup_screener.data import load_gene_scores
    from strategies.strategy_funnel_registry import score_candidates
    from strategies.calendar_factor import calendar_factor

    # 取当日 gene_scores
    genes = load_gene_scores(signal_date)
    if not genes:
        return {"signal_date": signal_date, "recommendations": 0, "note": "当日无 gene_scores 数据"}

    # 构造候选 + 策略分排序
    candidates = [
        {
            "code": g.code,
            "name": getattr(g, "name", ""),
            # factors dict 键名为中文（models.py:39 GeneScore.factors），
            # weight_set 用英文 factor_* 键名（strategy_weights.json），
            # 此处做中文取值→英文键名映射，与 backtest_lite.py:118 范式一致。
            "factors": {
                "factor_seal_rate": (g.factors or {}).get("封板率", 0) or 0,
                "factor_rebound_rate": (g.factors or {}).get("炸板后溢价", 0) or 0,
                "factor_red_rate": (g.factors or {}).get("红盘率", 0) or 0,
                "factor_premium_rate": (g.factors or {}).get("次日溢价率", 0) or 0,
                "factor_freq_score": (g.factors or {}).get("涨停频次", 0) or 0,
            },
        }
        for g in genes
    ]

    # S086 R7：取涨停池建 pool_item_map 传给 score_candidates，
    # 供 storm_reversal(fbt)/PRD 战法(lbc/zdp/p) 取因子 + R2 真实入场价 pool_item.p。
    # fetch_zt_pool → em_zt_topic_pool 走 em_get 限流 + 24h 缓存（防封底线）；
    # 失败/空池 → 空 map 降级，entry_price fallback gene.total_score + "价格代理"（A7）。
    pool_item_map: dict[str, dict] = {}
    try:
        from strategies.first_board_filter import fetch_zt_pool  # noqa: PLC0415
        for p in fetch_zt_pool(signal_date) or []:
            code = str(p.get("c", "") or "").strip()
            if code:
                pool_item_map[code] = p
    except Exception as exc:  # noqa: BLE001 — 取池失败降级空 map，不阻断前向测试
        logging.getLogger("vibe-research").warning(
            "forward_test 取涨停池建 pool_item_map 失败 %s: %s", signal_date, exc,
        )
    scored = score_candidates(candidates, weather_state, signal_date, pool_item_map)
    mult, _ = calendar_factor(signal_date)

    recommendations = [
        DailyRecommendation(
            signal_date=signal_date,
            code=s["code"],
            name=s.get("name", ""),
            strategy_code=s["strategy_code"],
            strategy_score=s["strategy_score"],
            weather_state=weather_state,
            position_multiplier=mult,
            recommended_position=round(5.0 * mult, 2),  # base 5% × 日历因子
        )
        for s in scored[:20]  # top-20 推荐（picks）
    ]

    count = record_daily_recommendations(signal_date, recommendations)

    # §44 60日复验窗口：记录当日全体涨停股 universe codes（收益 NULL，次日 record_universe_returns 回填）——诚实标注源，非接入阻断
    _record_universe_codes(signal_date, genes)

    return {
        "signal_date": signal_date,
        "recommendations": count,
        "universe_codes": len(genes),
        "weather_state": weather_state,
        "position_multiplier": mult,
    }


def _record_universe_codes(signal_date: str, genes: list) -> int:
    """记录当日全体涨停股 codes 到 universe_returns（收益 NULL，待次日回填）。

    INSERT OR IGNORE（UNIQUE signal_date,code）——仅记 code，不覆盖已回填收益的行。
    """
    _ensure_table()
    conn = sqlite3.connect(_DB, timeout=10)
    inserted = 0
    try:
        for g in genes:
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO universe_returns (signal_date, code) VALUES (?, ?)""",
                    (signal_date, g.code),
                )
                if cur.rowcount > 0:
                    inserted += 1
            except Exception:
                continue
        conn.commit()
    finally:
        conn.close()
    return inserted
