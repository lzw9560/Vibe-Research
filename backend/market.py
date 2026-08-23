"""市场总览数据层 —— 市场情绪 + 板块资金流（板块/大盘级公开数据，不涉个股推荐）。

省流量：全站共享一份缓存（TTL 默认 5 分钟），多个用户/多次打开只抓一次；
盘中 5 分钟刷新足够，非交易时段数据本就不变。数据源全免费、无 key。
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone, timedelta

import astock
import gstock

BEIJING = timezone(timedelta(hours=8))
_CACHE: dict = {}
_TTL = 300  # 5 分钟；全站共享，省数据源压力


def _cached(key: str, fn, valid=bool):
    """TTL 缓存。数据源故障的空结果不缓存（valid 判否），下次请求直接重试。"""
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    val = fn()
    if valid(val):
        _CACHE[key] = (now, val)
    return val


def _num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _sentiment(date: str | None = None) -> dict:
    """市场情绪（带 TTL 缓存，复用 _cached 5min）。

    S094 audit fix：防 latest 日双调用打两次 akshare——_emotion step8（T18）调 _sentiment(resolved)
    + _execute_sti_post_market L678 调 _sentiment(target)，同 15:30 run 内秒级双调。缓存后第二次命中。
    _cached valid=bool 默认：populated 缓存，空 {}（非 latest P0-1 返空）不缓存（重跑 P0-1 guard 便宜无 akshare）。
    """
    return _cached(f"sentiment:{date or 'latest'}", lambda: _sentiment_uncached(date))


def _sentiment_uncached(date: str | None = None) -> dict:
    """市场情绪：涨跌家数/涨停跌停/活跃度 + 大盘宽度、题材投机（客观数据机械分档）。

    Args:
        date: 可选日期字符串 YYYY-MM-DD。不传则取当前日期。

    ⚠️ 数据源语义陷阱（P0-1，2026-08-23 修复）：
        akshare ``stock_market_activity_legu()`` **只能查最新日，无法查历史**。
        历史 date 传入会被原实现静默忽略并返回最新日数据，导致"用今天的涨跌家数
        标在昨天的复盘上"的数据错位。此修复采用**诚实降级**：

        - date != 最近交易日 → 直接返回 ``{}``（不打 akshare，不拿今天数据错标历史日）
        - date=None 或 date == 最近交易日 → 保持原逻辑调 akshare 取最新数据

        历史 date 传入后调用方拿到空 dict，语义为"该日涨跌家数无源"，诚实缺失而非
        静默给最新日数据。已知 6 个调用方（daily_review/scheduled_tasks/workflow/
        limitup_sti）均用 ``.get("up", 0)`` / ``or {}`` / ``if not sentiment_data``
        等模式处理空返回，降级为 0 或兜底默认值。
    """
    # P0-1：历史日 akshare 无源，诚实返回空而非拿最新日数据错标历史
    if date is not None:
        try:
            from vr_paths import last_trading_date_str
            if date != last_trading_date_str():
                return {}
        except Exception:
            # vr_paths 取不到（极端故障）→ 不阻断，走原 akshare 流程
            # （宁可可能错位也不彻底打挂，下游有空返回兜底）
            pass
    try:
        # akshare 惰性导入（同 astock 模式）：未装时降级返回空，不挡整个服务启动
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        return {}
    up, down, flat = _num(d.get("上涨")), _num(d.get("下跌")), _num(d.get("平盘"))
    zt, zt_real = _num(d.get("涨停")), _num(d.get("真实涨停"))
    dt, dt_real = _num(d.get("跌停")), _num(d.get("真实跌停"))
    r = up / max(down, 1)
    if up < 600:
        breadth = "冰点"
    elif r < 0.7:
        breadth = "偏弱"
    elif r < 1.2:
        breadth = "中性"
    elif r < 2.5:
        breadth = "偏强"
    else:
        breadth = "普涨"
    speculation = "亢奋" if zt_real >= 100 else "活跃" if zt_real >= 60 else "普通" if zt_real >= 30 else "冰点"
    return {
        "up": up, "down": down, "flat": flat,
        "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
        "active": str(d.get("活跃度", "")),
        "breadth": breadth, "speculation": speculation,
        "date": str(d.get("统计日期", "")),
    }


def _sectors() -> list[dict]:
    """行业资金流（按净额降序）。不含领涨股等个股字段。

    S085 A5：换源东财 push2 clist 行业板块走 em_get（替代 akshare stock_fund_flow_industry
    打同花顺 raw requests 无熔断）。双 host 降级（push2→push2delay）。
    返 name/pct/net(亿)/inflow(None)/outflow(None)/firms——东财行业板块无 inflow/outflow
    字段（dead fields 保形状）。详见 eastmoney.sector_fund_flow docstring。
    """
    try:
        from data.sources.eastmoney import sector_fund_flow
        return sector_fund_flow()
    except Exception:
        return []


def get_overview() -> dict:
    """市场情绪 + 板块资金（含缓存）。资金轮动由前端从 sectors 头尾取。"""
    def build():
        return {
            "sentiment": _sentiment(),
            "sectors": _sectors(),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return _cached("overview", build, valid=lambda v: bool(v.get("sentiment") or v.get("sectors")))


def _parse_high_days(s) -> int:
    """解析同花顺 high_days '3天3板' → 3（取板数）。缺省/无法解析返 1。"""
    if not s:
        return 1
    import re
    m = re.search(r'(\d+)板', str(s))
    return int(m.group(1)) if m else 1


def _emotion(date: str | None = None) -> dict:
    """短线情绪（聚合口径，**零个股名**）：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    数据源＝东财涨停板四池（push2ex）。只把池子聚合成计数与比率，
    **不输出任何个股 code/name**——守产品「零标的」红线（个股清单是甩名单，不做）。

    S049：引入同花顺涨停揭秘作为交叉验证 + 降级备用源：
    - 降级：东财 zt 为空时，用同花顺重建 zt_count/max_boards（zb/dt/yzt 保持 None，不臆造）
    - 交叉验证：东财正常时，用同花顺 zt_count 做交叉验证，差异>5% 标注「数据源分歧」

    ⚠️ 数据源语义陷阱（P0-2，2026-08-23 修复）：
        东财 push2ex 池子在非交易日请求时会**静默回退**返回最近交易日数据，
        但返回的 ``date`` 字段标原始传入的非交易日（实测 08-21/22/23 三天字节级
        相同的 54 条涨停池）。东财池子 item 无日期字段，无法事后校验，故用
        **事前校验**：

        - date 显式传入且 ``not is_trading_day(date)`` → 直接返回 ``{}``
          （不查东财，避免静默回退错位）
        - date=None 的回溯定位模式（从今天往前回溯找最近交易日）保持不动——
          该路径本身只在有数据的交易日 resolve，不触发回退问题

        ⚠️ 盘前回退陷阱（P0-3，2026-08-23 修复）：
        东财 push2ex 在交易日盘前（< 15:00）当日数据尚未生成，对当日请求会
        **静默回退**到前一交易日数据（实测 08-21 盘前请求返 08-20 的 79 条
        涨停池），导致 ``_cache`` 存错日期的 zt_count。守卫：

        - date 显式传入 + 是今日交易日 + 当前时刻盘前（< 15:00）→ 返回 ``{}``
          （当日盘后数据未生成，不查东财；盘后 15:00+ 放行）
        - 历史交易日显式传入照常放行（盘后已生成，不触发回退）

    Args:
        date: 可选日期字符串 YYYY-MM-DD。不传则自动定位最近交易日。
    """
    # P0-2：显式传入非交易日 → 不查东财，避免静默回退错位
    if date is not None:
        try:
            from vr_paths import is_trading_day
            from datetime import date as _date_cls
            if not is_trading_day(_date_cls.fromisoformat(date)):
                return {}
        except (ValueError, TypeError):
            # 日期格式异常 → 走原流程的格式校验分支处理（不在此重复）
            pass
        except Exception:
            # vr_paths 取不到 → 不阻断，走原流程（宁可可能错位也不彻底打挂）
            pass

    # P0-3：交易日盘前当日请求 → 不查东财，避免 push2ex 盘前回退到 T-1
    # 东财 push2ex 盘前（< 15:00）当日涨停池未生成，返 T-1 数据致 _cache 存错日期。
    # 盘后（15:00+）当日数据已确定，放行。历史交易日显式传入不受限（已生成）。
    if date is not None:
        try:
            _now = datetime.now(BEIJING)
            _today_str = _now.strftime("%Y-%m-%d")
            if date == _today_str and _now.hour < 15:
                return {}
        except Exception:
            pass

    # S049 同花顺交叉验证 / 降级源标识（默认主源正常、未交叉验证）
    cross_source = None
    data_source = "eastmoney"
    ths = None  # 懒拉取：降级与交叉验证共用，只请求一次

    if date is not None:
        # 直接使用指定日期
        resolved = date.replace("-", "")
        # 验证格式
        try:
            datetime.strptime(resolved, "%Y%m%d")
        except ValueError:
            return {}
    else:
        # 定位最近交易日：从今天往前回溯，第一日有涨停池即取（非交易日/盘前返空则继续回溯）。
        today = datetime.now(BEIJING).date()
        resolved, zt_temp = "", []
        for back in range(8):
            d = (today - timedelta(days=back)).strftime("%Y%m%d")
            zt_temp = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
            if zt_temp:
                resolved = d
                break
        if not resolved:
            # 东财连续 8 日空（长假/数据源故障）→ 尝试同花顺降级定位最近交易日
            for back in range(8):
                d = (today - timedelta(days=back)).strftime("%Y%m%d")
                try:
                    ths_try = astock.ths_limit_up_pool(d) if hasattr(astock, "ths_limit_up_pool") else []
                except Exception:
                    ths_try = []
                if ths_try:
                    resolved = d
                    ths = ths_try  # 复用：后续不再重复请求
                    break
            if not resolved:
                return {}

    # T18：真实涨停数（akshare legu 源）——_sentiment 只能查最新日，历史日返 {}→None。
    # CRITICAL：传 dash-formatted resolved 日期（emotion 实际数据日），别裸调 _sentiment()
    # （=always-latest），否则今天 zt_real 标到非最新 emotion 日，重犯 P0-1/P0-2 日期错配。
    zt_real = _sentiment(f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}").get("zt_real")

    zt = astock.em_zt_topic_pool("getTopicZTPool", resolved, "fbt:asc")
    if not zt and date is None:
        # 主源空 → 同花顺降级（若 ths 已在定位阶段取到则复用，否则现取）
        if ths is None:
            try:
                ths = astock.ths_limit_up_pool(resolved) if hasattr(astock, "ths_limit_up_pool") else []
            except Exception:
                ths = []
        if not ths:
            return {}
        # 东财涨停池为空 → 同花顺降级重建 zt_count / max_boards（最小降级）
        zt_count = len(ths)
        boards = [_parse_high_days(s.get("high_days")) for s in ths]
        max_boards = max(boards) if boards else 0
        data_source = "ths_fallback"
        # zb/dt/yzt 无法从同花顺重建，保持空（不臆造）
        return {
            "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
            "zt_count": zt_count,
            "zt_real": zt_real,
            "dt_count": None,
            "zb_count": None,
            "max_boards": max_boards,
            "lianban_count": sum(1 for b in boards if b >= 2),
            "ladder": [],
            "lianban_stocks": [],  # 同花顺降级不重建个股榜（避免与东财口径混淆）
            "seal_rate": None,
            "break_rate": None,
            "promotion_rate": None,
            "yzt_count": None,
            "cross_source": None,  # 降级源无交叉验证对象
            "data_source": data_source,
        }

    # 如果指定日期但无数据，返回空
    if not zt:
        return {}

    zb = astock.em_zt_topic_pool("getTopicZBPool", resolved, "fbt:asc")    # 炸板池
    dt = astock.em_zt_topic_pool("getTopicDTPool", resolved, "fund:asc")   # 跌停池
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池

    boards = [_num(p.get("lbc")) or 1 for p in zt]      # 每只连板数（缺省按 1 板）
    lianban = [b for b in boards if b >= 2]             # 2 板及以上（连板）
    # 连板梯队：2/3/4/5+ 各多少家（5 代表 5 板及以上），只保留有家数的档
    tiers = Counter(min(b, 5) for b in lianban)
    ladder = [{"boards": b, "count": tiers[b], "plus": b >= 5} for b in sorted(tiers)]

    # 连板股清单（2 板+，客观公开榜单数据；按连板数、成交额降序）。
    # 产品定位调整（2026-07-05）：从「零标的」→「展示客观榜单但不推荐/不预测/不评分」。
    lianban_stocks = sorted(
        ({
            "code": str(p.get("c", "")), "name": p.get("n", ""),
            "boards": _num(p.get("lbc")) or 1,
            "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
            "pct": round(astock._numf(p.get("zdp")) or 0, 2),
            "amount": astock._numf(p.get("amount")),      # 成交额,元（'-' 占位归一为 None，防排序对 str 取负崩溃）
            "float_cap": astock._numf(p.get("ltsz")),     # 流通市值,元
            "industry": p.get("hybk", ""),  # 概念/行业
        } for p in zt if (_num(p.get("lbc")) or 1) >= 2),
        key=lambda x: (-x["boards"], -(x["amount"] or 0)),
    )

    zt_count, zb_count, yzt_count = len(zt), len(zb), len(yzt)
    attempts = zt_count + zb_count                       # 尝试涨停 = 封住 + 炸板
    seal_rate = round(zt_count / attempts, 3) if attempts else None      # 封板率
    break_rate = round(zb_count / attempts, 3) if attempts else None     # 炸板率
    # 晋级率＝今日 2 板+（＝昨涨停今又停）÷ 昨日涨停家数
    promotion_rate = round(len(lianban) / yzt_count, 3) if yzt_count else None

    # S049 交叉验证：同花顺涨停家数 vs 东财（主源正常时）
    try:
        ths = astock.ths_limit_up_pool(resolved) if hasattr(astock, "ths_limit_up_pool") else []
        if ths:
            ths_count = len(ths)
            diff_pct = abs(ths_count - zt_count) / max(zt_count, 1) * 100
            cross_source = {
                "ths_zt_count": ths_count,
                "diff_pct": round(diff_pct, 1),
                "divergent": diff_pct > 5,  # 差异>5% 标注分歧
            }
            data_source = "eastmoney+ths_cross"
    except Exception:
        cross_source = None  # 同花顺请求失败不影响主源数据返回

    return {
        "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
        "zt_count": zt_count,
        "zt_real": zt_real,
        "dt_count": len(dt),
        "zb_count": zb_count,
        "max_boards": max(boards) if boards else 0,
        "lianban_count": len(lianban),
        "ladder": ladder,
        "lianban_stocks": lianban_stocks,
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_count": yzt_count,
        "cross_source": cross_source,
        "data_source": data_source,
    }


def get_short_term_emotion() -> dict:
    """短线情绪（含缓存，5 分钟）。"""
    return _cached("emotion", _emotion)


def get_turnover_top() -> dict:
    """全市场成交额榜 Top20（客观公开榜单，含缓存 5 分钟）。"""
    def build():
        return {
            "stocks": astock.market_turnover_rank(20),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }
    return _cached("turnover_top", build, valid=lambda v: bool(v.get("stocks")))


def get_global_indices() -> list[dict]:
    """全球指数快照（美股 / 港股，含缓存 5 分钟）。空结果不缓存。"""
    return _cached("global_indices", gstock.global_indices, valid=bool)


def get_global_macro() -> dict:
    """全球宏观/地缘分块（S020 R5）：商品/外汇/CII/热点升级。

    worldmonitor 派生，**不与东财板块资金流混排**（不同语义），单独分块供前端独立渲染。
    worldmonitor fetcher 自带 TTL 缓存（24h/5min/1h），故此处**不再套 market._cached**
    （grill #6：双层缓存 TTL 打架——外层 5min 使内层 24h 永不生效）。
    worldmonitor 不可达 → 各子块空（诚实缺省，不臆造、不抛）。
    合成分（CII/热点）标 ``source: worldmonitor_composite``，作输入之一不作唯一依据。
    """
    def build():
        try:
            from data.sources import worldmonitor as wm
        except Exception:
            return {"commodities": [], "fx": [], "cii": {}, "hotspots": [], "updated": None,
                    "source": "worldmonitor", "available": False}
        # 单次取 market_data，本地分区（避免重复调用触发 breaker/限流）
        md = wm.parse_market_data(wm.fetch_market_data())
        commodity_syms = ("CL", "XAU", "HG", "BRENT", "WTI", "GOLD", "COPPER")
        fx_syms = ("DXY", "USDCNH", "USD-CNH", "EURUSD")
        commodities = [m for m in md if m.get("symbol") in commodity_syms]
        fx = [m for m in md if m.get("symbol") in fx_syms]
        cii = wm.parse_country_risk(wm.fetch_country_risk())
        hotspots = wm.parse_hotspot_escalation(wm.fetch_hotspot_escalation())
        return {
            "commodities": commodities,
            "fx": fx,
            "cii": cii,
            "hotspots": hotspots,
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
            "source": "worldmonitor",
            "available": bool(commodities or fx or cii.get("countries") or hotspots),
        }
    return build()
