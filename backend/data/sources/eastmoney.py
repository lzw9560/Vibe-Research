# -*- coding: utf-8 -*-
"""S008 东财源（em_get 系；研报/热门概念已统一走 em_get）。

从 ``astock.py`` 迁出。取数逻辑一字不改，仅换文件组织。

**防封底线（CLAUDE.md §1.2）**：东财 push2/push2ex/push2his/datacenter/reportapi/emappdata
端点全部走 ``data.transport.eastmoney_get``（限流 QPS≤2 + 熔断 + 直连/代理探测），
**不裸调 requests**。S164 R3：研报（reportapi，GET）/热门概念（emappdata，POST+json）
已从直 requests 迁 em_get——统一防封路径。
np-anotice（公告）已迁 em_get——S148 审计：st_play_radar/first_board_filter 遍历
ST/首板候选每日数百次裸调 → §3 防封底线违规，公告不再例外（原"非封 IP 域"假设被放大证伪）。

公开函数（``astock`` 门面同名 re-export，返回 raw dict 不变）：
- em_get 系：``em_zt_topic_pool``、``market_turnover_rank``、``eastmoney_datacenter``
  及 8 下游（margin_trading / block_trade / holder_num_change / dividend_history /
  stock_fund_flow_120d / dragon_tiger_board / lockup_expiry / concept_blocks / industry_comparison）
  + ``eastmoney_reports`` / ``eastmoney_industry_reports`` / ``announcements`` /
  ``hot_concepts``（S164 R3 迁入；hot_concepts 走 POST+json）
- ``pdf_url``：纯 URL 拼接，无请求
- 五档买卖盘：``bids``（push2/push2delay 双 host 降级，走 em_get 限流；S085 D2）
- 同花顺交叉验证源：``ths_limit_up_pool``（涨停揭秘，dataapi 域，非东财防封域；
  走 ``_ths_get`` 限流——独立 ths breaker + 0.5s 间隔 + 抖动，不裸调 requests；
  仅供 market._emotion 交叉验证/降级备用，不进主取数路径）
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta

import requests
from circuit_breaker import get_breaker

from data.transport import eastmoney_get as em_get  # 防封底线：走限流/熔断/代理
from ._common import UA

_REPORT_API = "https://reportapi.eastmoney.com/report/list"
_PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
# 东财 push2/push2his 端点公开 token（缺则端点返空或断连——S044 探测发现 astock 旧函数缺 ut 是 bug，非端点宕）
_PUSH2_UT = "fa5fd1943c7b386f172d6893dbbd1"


# 研报请求头（原 _report_session 设的 UA + Referer，迁 em_get 后显式传入保持一致）
_REPORT_HEADERS = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}


def eastmoney_reports(code: str, max_pages: int = 3) -> list[dict]:
    """按个股代码拉研报列表（qType=0）。

    S164 R3：走 ``em_get`` 限流/熔断/代理探测防封（原 ``_report_session().get()`` 裸调）。
    em_get 自带 0.3s+抖动串行限流，去掉原手写 ``time.sleep(0.3)``（避免双重节流）。
    """
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        r = em_get(_REPORT_API, params=params, headers=_REPORT_HEADERS, timeout=30)
        d = r.json()
        rows = d.get("data") or []
        if not rows:
            break
        out.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
    return out


def eastmoney_industry_reports(keywords: list[str] | None = None, days: int = 90, max_pages: int = 3) -> list[dict]:
    """按行业拉研报（qType=1）——适合产业链 / 主题级检索。keywords 在标题上过滤。

    S164 R3：走 ``em_get`` 限流/熔断/代理探测防封（原 ``_report_session().get()`` 裸调）。
    """
    from datetime import date, timedelta

    end = date.today()
    begin = end - timedelta(days=days)
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin.isoformat(), "endTime": end.isoformat(),
            "pageNo": str(page), "fields": "", "qType": "1",
            "orgCode": "", "code": "", "rcode": "",
        }
        r = em_get(_REPORT_API, params=params, headers=_REPORT_HEADERS, timeout=30)
        rows = r.json().get("data") or []
        if not rows:
            break
        out.extend(rows)
    if keywords:
        out = [r for r in out if any(k in r.get("title", "") for k in keywords)]
    return out


def pdf_url(info_code: str) -> str:
    return _PDF_TPL.format(info_code=info_code)


def announcements(code: str, limit: int = 15) -> list[dict]:
    """个股近期公告（东财 np-anotice，走 em_get 限流/熔断/代理探测防封）。返回 日期/标题/类型/详情链接。

    S148 审计修复：原裸 ``import requests; requests.get`` 绕过 em_get——st_play_radar
    遍历 ~325 ST 股 + first_board_filter score_dim9_event 遍历 ~52 首板候选，每日定时
    数百次裸调东财 → §3/§1.2 防封底线违规（封 IP 波及涨停池/龙虎榜/行情全链）。改走
    em_get（本模块 line 33 已 import）：0.3s/次串行限流 + 5 失败熔断 + 直连/代理探测。
    """
    r = em_get(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        params={"sr": -1, "page_size": limit, "page_index": 1, "ann_type": "A",
                "client_source": "web", "stock_list": code, "f_node": 0, "s_node": 0},
        headers={"User-Agent": UA}, timeout=20,
    )
    lst = (r.json().get("data") or {}).get("list") or []
    out = []
    for a in lst:
        cols = [c.get("column_name") for c in (a.get("columns") or []) if c.get("column_name")]
        art = a.get("art_code", "")
        out.append({
            "date": (a.get("notice_date", "") or "")[:10],
            "title": a.get("title", ""),
            "type": cols[0] if cols else "",
            "url": f"https://data.eastmoney.com/notices/detail/{code}/{art}.html" if art else "",
        })
    return out


# ---------------------------------------------------------------------------
# 打板层 · 涨停/炸板/跌停/昨涨停 原始池（东财 push2ex，走 em_get 限流）
# ⚠️ 合规：原始池含个股 code/name —— 仅供 market.py 聚合成【不含个股名】的短线情绪指标。
#    切勿把原始池直接接成 API/UI（会甩个股名单、破产品「零标的」红线）。
# ---------------------------------------------------------------------------
# 日 K 通用公开 token（非涨停池专属）：push2his kline/get 用此 ut（akshare stock_cyq_em
# 验证），S114 chip_distribution 自建取数复用。非密钥，硬编码常量。fflow 用 _PUSH2_UT。
_ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"

# S103：涨停池缓存 TTL 分级（盘中短保新鲜 / 盘后中定盘 / 历史长省请求）。
# 原单一 24h TTL 对盘中场景致命：seal_intraday 60s 轮询命中 24h 缓存返 09:25 陈旧首帧。
_ztb_cache: dict[tuple[str, str, str], tuple[float, list[dict]]] = {}
_ZTB_CACHE_TTL_INTRADAY = 60      # 盘中 60s（保新鲜，对齐 S055 seal_intraday 采集节奏）
_ZTB_CACHE_TTL_POSTMARKET = 3600  # 今日盘后 1h（定盘后稳定）
_ZTB_CACHE_TTL_HISTORY = 86400    # 历史日 / 非交易日 24h（无变化，省请求）
# 向后兼容别名（S103 前单一 24h TTL；旧消费者 astock._ZTB_CACHE_TTL 仍可取）
_ZTB_CACHE_TTL = _ZTB_CACHE_TTL_HISTORY


def _ztb_cache_ttl(date: str) -> int:
    """根据 date + 当前时刻选 TTL（S103 盘中陈旧快照根因治理）。

    判定顺序（grill 第 4 轮锁定）：
    1. 当前非交易日（is_trading_day(date.today())）→ 24h（不管查什么 date，都稳定）
    2. date != 今日交易日紧凑日期 → 历史日 24h
    3. date == 今日 + 当前盘中 → 60s
    4. date == 今日 + 当前盘后 → 1h

    用 is_trading_day(date.today()) 而非 last_trading_date_str() 判非交易日——
    否则周六查周五数据被错判"今日盘后"用 1h（grill 第 4 轮）。
    """
    from vr_paths import is_intraday_time, is_trading_day, last_trading_date_str
    if not is_trading_day():                                  # 当前非交易日 → 一律 24h
        return _ZTB_CACHE_TTL_HISTORY
    if date != last_trading_date_str().replace("-", ""):     # 历史日
        return _ZTB_CACHE_TTL_HISTORY
    if is_intraday_time():                                    # 今日盘中
        return _ZTB_CACHE_TTL_INTRADAY
    return _ZTB_CACHE_TTL_POSTMARKET                          # 今日盘后


def em_zt_topic_pool(endpoint: str, date: str, sort: str = "fbt:asc",
                     raise_on_failure: bool = False) -> list[dict]:
    """东财涨停板行情中心原始池（push2ex）。
    endpoint: getTopicZTPool(涨停) / getTopicZBPool(炸板) / getTopicDTPool(跌停) / getYesterdayZTPool(昨涨停)
    date: YYYYMMDD 交易日。非交易日 / 参数错 → []。
    池内每项字段含 lbc(连板数) / zbc(炸板次数) / hybk(行业) 等。
    缓存（S103）：同一 (endpoint, date, sort) 结果按 _ztb_cache_ttl 分级缓存（盘中 60s /
    盘后 1h / 历史 24h）。空结果不缓存——失败/熔断返空不毒缓存，下次请求直接重试。

    S131 R5：``raise_on_failure=True`` 时源断（em_get 断连/限流/JSON 错）即 re-raise
    （非吞成 []），让承重 caller 的 ``get_with_fallback_meta``（extreme_market_detector:128
    已范式）设 fetch_ok=False → data_status='missing'（源断不伪装"平静市"）。
    默认 False 向后兼容（既有吞 [] 行为，mock 测试不破）。空不缓存逻辑不变。
    防封安全：取数路径仍走 em_get 限流/熔断/代理，仅源断时 raise 而非 swallow []。
    """
    cache_key = (endpoint, date, sort)
    now = time.time()
    ttl = _ztb_cache_ttl(date)
    cached = _ztb_cache.get(cache_key)
    if cached and now - cached[0] < ttl:
        return cached[1]

    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": _ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        result = (r.json().get("data") or {}).get("pool") or []
        # S103 R1：空结果不缓存——失败/真空都不写缓存，下次请求直接重试。
        # （grill 第 2 轮：实测 push2ex 成功 response 恒 pool 非空，故空只走失败路径，
        #  `if result` 与"成功缓存/失败不缓存"语义吻合。盘中 09:25 真空盲区验收阶段补测。）
        if result:
            _ztb_cache[cache_key] = (now, result)
        return result
    except Exception:
        # S131 R5：raise_on_failure=True 时 re-raise（源断不伪装合法空 []），
        # 默认 False 仍返 []（向后兼容）。异常时不缓存——让上层 _emotion 的
        # 5min TTL 重试机制生效（原实现缓存空结果 24h 致瞬态故障后恒空）。
        if raise_on_failure:
            raise
        return []


def _numf(v):
    """东财数值字段可能是 '-'（停牌/无数据）→ 归一成 float 或 None。"""
    return v if isinstance(v, (int, float)) else None


# ---------------------------------------------------------------------------
# 同花顺涨停揭秘（dataapi.10jqka，非东财防封域）
# S049 新增：仅供 market._emotion 交叉验证 + 降级备用，不进主取数路径。
# S085 D4：走 _ths_get 限流（独立 ths breaker + 0.5s 间隔 + 抖动），不裸调 requests。
# 请求频率另受 _emotion 5min TTL 缓存约束（同缓存内只发一次）。请求失败返 []，不崩主流程。
# ---------------------------------------------------------------------------
# 同花顺请求最小间隔（秒）——同花顺非东财域，独立防封节流（不复用 em_get 限流）
_THS_MIN_INTERVAL = 0.5
_ths_lock = threading.Lock()
_ths_last_call = [0.0]   # Lock 守护的可变单元素列表（防并发击穿 0.5s 间隔）


def _ths_get(url: str, params: dict | None = None, headers: dict | None = None,
             timeout: int = 10):
    """同花顺专用限流请求（dataapi.10jqka 域，非东财，em_get 不能包）。

    独立失败计数 ``get_breaker("ths")``（新 breaker 名，与 eastmoney 隔离）+
    ``_THS_MIN_INTERVAL`` 最小间隔 + 抖动，复用 UA。
    ``_ths_lock`` 串行化 wait/sleep/时间戳更新三步原子（防并发击穿 0.5s 间隔）。
    失败 raise（消费方 ths_limit_up_pool 已有 try/except 兜 []）。
    """
    breaker = get_breaker("ths")
    if not breaker.allow_request():
        raise RuntimeError(f"[CircuitBreaker:ths] 同花顺数据源熔断中，快速失败（{url}）")
    with _ths_lock:  # 原子化：算 wait → sleep → 设时间戳（防并发竞态击穿 0.5s 间隔）
        wait = _THS_MIN_INTERVAL - (time.time() - _ths_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.3))
        _ths_last_call[0] = time.time()
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        breaker.record_success()
        return r
    except Exception:
        breaker.record_failure()
        raise


def ths_limit_up_pool(date: str) -> list[dict]:
    """同花顺涨停揭秘（涨停原因 + 封板质量增强源）。date=YYYYMMDD。

    S085 D4：走 ``_ths_get`` 限流（独立 ths breaker + 0.5s 间隔 + 抖动），不裸调 requests。
    返每只: ``code`` / ``reason``(涨停原因题材) / ``high_days``(几天几板,字符串如"3天3板")。
    仅消费方读取的 3 字段（market high_days / first_board_filter code+reason /
    sector_cycle reason / build_concept_map code）；9 死字段精简（无下游消费）。

    用途：东财涨停池为空时降级补 zt_count/max_boards；主源正常时做 zt_count 交叉验证。
    ⚠️ 不臆造：zb/dt/yzt 无法从此源重建，调用方保持 None。
    """
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
    params = {
        "page": 1, "limit": 200,
        "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
        "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": "0",
        "date": date,
    }
    try:
        r = _ths_get(url, params=params, headers={"User-Agent": UA}, timeout=10)
        info = (r.json().get("data") or {}).get("info", [])
    except Exception as e:
        # 不崩主流程：降级返空，主源数据正常返回
        import logging
        logging.getLogger(__name__).warning("同花顺涨停揭秘请求失败: %s", e)
        return []
    return [{
        "code": it.get("code"),
        "reason": it.get("reason_type", ""),
        "high_days": it.get("high_days", ""),
    } for it in info]


def sector_fund_flow(raise_on_failure: bool = False) -> list[dict]:
    """行业板块资金流（东财 push2 clist，fs=m:90+t:2 行业板块，~100 个行业）。

    S085 A5：替代 market._sectors 的 akshare stock_fund_flow_industry（打同花顺 raw requests 无熔断）。
    走 em_get + 双 host 降级（push2→push2delay，同 market_turnover_rank 范式）。
    返每板块：name/f14(名) / pct/f3(涨跌幅) / net(亿, f62元/1e8) / inflow=None / outflow=None /
    firms(f104+f105 涨跌家数)。

    S131 R7：``raise_on_failure=True`` 时双 host 均 raise（断连/限流）即 re-raise
    （非吞成 []），让 market._sectors/overview build 标 sectors_status='missing'
    （源断不伪装"无板块资金流"）。双 host 均返空但无异常（真无板块，罕见）仍返 []
    （合法空不 raise，对齐 S119 HTTP-成功-空=合法 范式）。默认 False 向后兼容。
    防封安全：取数路径仍走 em_get 限流/熔断/代理，仅源断时 raise 而非 swallow []。

    probe（2026-08-19 live）：akshare 打同花顺非东财（§1.2 东财 scope 不强制——A5 是防封工程改进，
    非选股 bug）；东财 push2 直连断、push2delay 可达（双 host 降级必要）；东财行业板块无 inflow/outflow
    字段（只 f62 净额）；sector_* 全 dead fields（无下游消费）→ inflow/outflow=None 保形状无影响。
    """
    params = {"pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
              "fid": "f62",  # 按主力净额降序
              "fs": "m:90+t:2",
              "fields": "f12,f14,f3,f62,f104,f105", "ut": _PUSH2_UT}
    last_exc: Exception | None = None
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            r = em_get(f"https://{host}/api/qt/clist/get", params=params,
                       headers={"User-Agent": UA}, timeout=12)
            items = (r.json().get("data") or {}).get("diff") or []
            if isinstance(items, dict):
                items = list(items.values())
            if items:
                return [{
                    "name": str(d.get("f14", "")),
                    "pct": round(_numf(d.get("f3")) or 0.0, 2),
                    "net": round((_numf(d.get("f62")) or 0.0) / 1e8, 2),  # 元→亿
                    "inflow": None,   # 东财行业板块无此字段（dead field 保形状）
                    "outflow": None,
                    "firms": (_numf(d.get("f104")) or 0) + (_numf(d.get("f105")) or 0),
                } for d in items]
        except Exception as exc:
            last_exc = exc
            continue  # 断连/限流 → 下一 host
    # S131 R7：双 host 均失败（断连/限流，last_exc 非 None）→ raise_on_failure=True 时
    # re-raise（让 _sectors/overview 标 sectors_status='missing'，非合法空 []）。
    # 双 host 均返空但无异常（真无板块，罕见）仍返 []（合法空不 raise）。
    if raise_on_failure and last_exc is not None:
        raise last_exc
    return []


def market_turnover_rank(n: int = 20, raise_on_failure: bool = False) -> list[dict]:
    """全市场成交额榜（沪深京 A 股按成交额降序 TopN）。

    东财行情中心 clist。**push2(实时) 不可达时降级 push2delay(延迟行情，日榜场景足够)**。
    返回每只: code / name / price / pct / amount(成交额,元) / mcap(总市值,元) /
    float_cap(流通市值,元) / industry。
    ⚠️ 这是客观公开榜单数据（东财/同花顺同款），产品侧只做客观展示——非推荐、非预测、不评分。

    S131 R6：``raise_on_failure=True`` 时双 host 均 raise（断连/限流，diff 终空）即 re-raise
    （非吞成 []），让 get_turnover_top/build 标 data_status='missing'（源断不伪装"无成交额榜"）。
    双 host 均返空但无异常（真无数据，罕见）仍返 []（合法空不 raise，对齐 S119 范式）。
    默认 False 向后兼容。防封安全：取数路径仍走 em_get 限流/熔断/代理。
    """
    params = {"pn": 1, "pz": n, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f6",
              "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
              "fields": "f12,f14,f2,f3,f6,f20,f21,f100"}
    diff: list[dict] = []
    last_exc: Exception | None = None
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            r = em_get(f"https://{host}/api/qt/clist/get", params=params,
                       headers={"User-Agent": UA}, timeout=12)
            diff = (r.json().get("data") or {}).get("diff") or []
            if diff:
                break
        except Exception as exc:
            last_exc = exc
            continue
    # S131 R6：双 host 均失败（断连/限流，diff 终空 + last_exc 非 None）→ raise_on_failure=True
    # 时 re-raise（让 get_turnover_top 标 data_status='missing'，非合法空 []）。
    # 双 host 均返空但无异常（真无数据）仍返 []（合法空不 raise）。
    if raise_on_failure and not diff and last_exc is not None:
        raise last_exc
    return [{
        "code": str(d.get("f12", "")), "name": d.get("f14", ""),
        "price": _numf(d.get("f2")), "pct": _numf(d.get("f3")),
        "amount": _numf(d.get("f6")), "mcap": _numf(d.get("f20")),
        "float_cap": _numf(d.get("f21")), "industry": d.get("f100", "") or "",
    } for d in diff]


_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def eastmoney_datacenter(report_name: str, columns: str = "ALL", filter_str: str = "",
                         page_size: int = 50, sort_columns: str = "", sort_types: str = "-1",
                         raise_on_failure: bool = False) -> list[dict]:
    """东财数据中心统一查询 —— 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用（已内置限流）。

    raise_on_failure=True 时，em_get/.json() 抛异常（源断/限流/JSON 错）即 re-raise（非吞成 []），
    让下游 get_with_fallback_meta 据此设 fetch_ok=False（S119 恢复 S112 fetch_ok 前提——
    源端吞异常曾令 fetch_ok 恒 True、源断伪装"未上榜 ok"）。HTTP 成功但 result.data 空
    （真无数据）仍返 []（合法空，不抛）。默认 False = 既有吞异常行为（向后兼容，保护其他消费者）。
    """
    params = {
        "reportName": report_name, "columns": columns, "filter": filter_str,
        "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types, "source": "WEB", "client": "WEB",
    }
    try:
        d = em_get(_DATACENTER_URL, params=params, timeout=15).json()
    except Exception:
        if raise_on_failure:
            raise
        return []
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def margin_trading(code: str, page_size: int = 30) -> list[dict]:
    """融资融券明细（日级）：融资余额 / 融资买入 / 融券余额 / 两融合计。"""
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX", filter_str=f'(SCODE="{code}")',
        page_size=page_size, sort_columns="DATE", sort_types="-1")
    return [{
        "date": str(r.get("DATE", ""))[:10],
        "rzye": r.get("RZYE", 0), "rzmre": r.get("RZMRE", 0), "rzche": r.get("RZCHE", 0),
        "rqye": r.get("RQYE", 0), "rqmcl": r.get("RQMCL", 0),
        "rzrqye": r.get("RZRQYE", 0),
    } for r in data]


def block_trade(code: str, page_size: int = 20) -> list[dict]:
    """大宗交易：成交价 / 折溢价率 / 量 / 买卖方营业部。"""
    data = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1")
    rows = []
    for r in data:
        close = r.get("CLOSE_PRICE") or 0
        deal = r.get("DEAL_PRICE") or 0
        rows.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "price": deal, "close": close,
            "premium_pct": round((deal / close - 1) * 100, 2) if close else 0,
            "vol": r.get("DEAL_VOLUME", 0), "amount": r.get("DEAL_AMT", 0),
            "buyer": r.get("BUYER_NAME", ""), "seller": r.get("SELLER_NAME", ""),
        })
    return rows


def holder_num_change(code: str, page_size: int = 10) -> list[dict]:
    """股东户数变化（季度级）：户数 / 环比 / 户均持股。持续减少 = 筹码集中。"""
    data = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="END_DATE", sort_types="-1")
    return [{
        "date": str(r.get("END_DATE", ""))[:10],
        "holder_num": r.get("HOLDER_NUM", 0),
        "change_ratio": r.get("HOLDER_NUM_RATIO", 0),
        "avg_shares": r.get("AVG_FREE_SHARES", 0),
    } for r in data]


def dividend_history(code: str, page_size: int = 20) -> list[dict]:
    """分红送转历史：每股派息（税前）/ 每10股转增 / 每10股送股 / 进度。"""
    data = eastmoney_datacenter(
        "RPT_SHAREBONUS_DET", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size, sort_columns="EX_DIVIDEND_DATE", sort_types="-1")
    return [{
        "date": str(r.get("EX_DIVIDEND_DATE", ""))[:10],
        "bonus_rmb": r.get("PRETAX_BONUS_RMB", 0),
        "transfer_ratio": r.get("TRANSFER_RATIO", 0),
        "bonus_ratio": r.get("BONUS_RATIO", 0),
        "plan": r.get("ASSIGN_PROGRESS", ""),
    } for r in data]


def stock_fund_flow_120d(code: str, date: str | None = None) -> list[dict]:
    """个股资金流（日级，最近 120 交易日）：主力 / 小单 / 中单 / 大单 / 超大单净流入（元）。

    S049a：push2his 断连时降级 push2delay（东财延迟镜像，同 path 同 ut 仅 host 不同；
    资金流为日级盘后数据，延迟无实质影响）。首个返非空 klines 的 host 即用；都失败返空。
    S085 A6 残留：date 传则过滤 flows ≤ date（修 topology replay 误取今日；fund_flow.py
    走 A6 内部过滤不复用此参数，topology/risk_models 实时取最新不传 date）。
    资金流 fallback：push2his/push2delay 都失败时降级新浪 MoneyFlow（ssl_qsfx_lscjfb，
    四档细分齐全，单位元一致）。本机 push2his 被拒连时由新浪兜底（审查 M4/P4）。
    S111 R3：每行带 ``source`` provenance（对齐 market._emotion data_source 字段范式）——
    东财行 'eastmoney'，新浪降级行 'sina_fallback'。下游可见跨源降级，破坏默认取主源
    契约时能识别（新浪主力/超大单口径与东财 f52 聚合算法有细微差异，max_abs 不混算）。
    """
    market_code = 1 if code.startswith("6") else 0
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
        "ut": _PUSH2_UT,
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    for host in ("push2his.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            d = em_get(f"https://{host}/api/qt/stock/fflow/daykline/get",
                       params=params, headers=headers, timeout=15).json()
        except Exception:
            continue  # 断连/限流 → 下一 host
        rows = _parse_fflow_klines(d)
        if date and rows:  # S085 A6 残留：过滤 ≤ date（replay 取该日或之前最近）
            rows = [r for r in rows if (r.get("date") or "")[:10] <= date]
        # push2delay 可能只返 1 条当天数据（延时镜像不完整）——数据量不足时也降级
        if rows and len(rows) >= 5:  # 至少 5 条才视为有效历史数据
            return _with_source(rows, "eastmoney")
    # 东财双 host 均失败/数据不足 → 新浪 MoneyFlow 降级
    # S111 R3：新浪降级路径加 source provenance——返回值带来源标识，让下游可见
    # '这是新浪降级数据非东财'（新浪主力/超大单口径与东财 f52 聚合算法有细微差异，
    # max_abs 跨源混算失真）。对齐 market._emotion data_source='ths_fallback' 字段范式
    # （kline_resolver (bars,source_name) 元组范式会改签名破坏 6 调用方——risk_models /
    # routers / fund_flow / mappers / topology / validation——弱合规下不可行；字段范式
    # 加性兼容、下游默认取主源契约时可见、不臆造）。
    rows = _sina_fund_flow_fallback(code, 120)
    if date and rows:
        rows = [r for r in rows if (r.get("date") or "")[:10] <= date]
    # S115 R2：新浪降级路径加对称 len>=5 门（对齐东财 :466）——新浪返 <5 条
    # （新股/稀疏覆盖）非有效 120d 历史，返 [] 落回 risk_models not history→
    # _empty_capital_flow(missing) 诚实返空（S111 R3 范式）；避免 1-4 条当 120d
    # 历史算 max_abs 致 signal 满格 ±1.0 → adjustment 扭曲 risk_level（口径漂移~25×）
    if rows and len(rows) >= 5:
        return _with_source(rows, "sina_fallback")
    return []


def _sina_fund_flow_fallback(code: str, num: int = 120) -> list[dict]:
    """新浪 MoneyFlow 降级取数（东财 push2his/push2delay 均失败时）。

    接口：MoneyFlow.ssl_qsfx_lscjfb（四档细分齐全：超大/大/中/小单净流入）
    单位：元（与东财一致）
    无需认证；IP 限流建议间隔 ≥0.2s（本函数是 fallback 低频路径，不做额外限流）
    """
    import json as _json

    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    daima = f"{prefix}{code}"
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_lscjfb"
    sina_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        import requests
        r = requests.get(url, params={"page": "1", "num": str(num), "sort": "opendate", "asc": "0", "daima": daima},
                         headers=sina_headers, timeout=10)
        r.encoding = "gbk"
        text = r.text.strip()
        # 新浪返回类 JSON（可能带 PHP 前缀），截取 [ 到 ] 之间内容
        start, end = text.index("["), text.rindex("]")
        data = _json.loads(text[start:end + 1])
    except Exception:
        return []

    rows = []
    for item in data:
        def _f(v):
            try:
                return float(v) if v not in ("-", "", None) else 0.0
            except (ValueError, TypeError):
                return 0.0
        rows.append({
            "date": item.get("opendate", ""),
            "main_net": _f(item.get("netamount")),
            "small_net": _f(item.get("r3_net")),
            "mid_net": _f(item.get("r2_net")),
            "large_net": _f(item.get("r1_net")),
            "super_net": _f(item.get("r0_net")),
        })
    # 新浪按日期降序（最新在前），翻转为升序与东财口径一致
    rows.reverse()
    return rows


def _parse_fflow_klines(d: dict) -> list[dict]:
    """fflow/daykline klines 解析（S049a 从 stock_fund_flow_120d 抽出，降级复用）。"""
    rows = []
    for line in (d or {}).get("data", {}).get("klines", []):
        p = line.split(",")
        if len(p) >= 6:
            def _f(x):
                try:
                    return float(x) if x not in ("-", "") else 0.0
                except ValueError:
                    return 0.0
            rows.append({
                "date": p[0], "main_net": _f(p[1]), "small_net": _f(p[2]),
                "mid_net": _f(p[3]), "large_net": _f(p[4]), "super_net": _f(p[5]),
            })
    return rows


def _with_source(rows: list[dict], source: str) -> list[dict]:
    """给每行加 source provenance（immutable：新建 dict 不改原行）。

    S111 R3：stock_fund_flow_120d 返回值带来源标识，让下游可见'这是新浪降级数据
    非东财'。对齐 market._emotion data_source='ths_fallback' 字段范式——东财行
    source='eastmoney'，新浪降级行 source='sina_fallback'。下游（risk_models /
    cross_validate）默认取主源契约时可据此识别降级数据不混算。
    """
    return [{**r, "source": source} for r in rows]


# ---------------------------------------------------------------------------
# 五档买卖盘（东财 push2/push2delay，走 em_get 限流）—— S085 D2
# ---------------------------------------------------------------------------
# akshare stock_bid_ask_em 原汁 fields 串（含 f120/f262/f530 高位字段触发五档自动返回，
# 最小/空 fields 返空——勿自造精简集）。
_BID_FIELDS = (
    "f120,f121,f122,f174,f175,f59,f163,f43,f57,f58,f169,f170,f46,f44,f51,"
    "f168,f47,f164,f116,f60,f45,f52,f50,f48,f167,f117,f71,f161,f49,f530,"
    "f135,f136,f137,f138,f139,f141,f142,f144,f145,f147,f148,f140,f143,f146,"
    "f149,f55,f62,f162,f92,f173,f104,f105,f84,f85,f183,f184,f185,f186,f187,"
    "f188,f189,f190,f191,f192,f107,f111,f86,f177,f78,f110,f262,f263,f264,f267,"
    "f268,f255,f256,f257,f258,f127,f199,f128,f198,f259,f260,f261,f171,f277,f278,"
    "f279,f288,f152,f250,f251,f252,f253,f254,f269,f270,f271,f272,f273,f274,f275,"
    "f276,f265,f266,f289,f290,f286,f285,f292,f293,f294,f295"
)
# 买1→买5 / 卖1→卖5（akshare 口径：buy1=f19/f20 ... buy5=f11/f12；
# sell1=f39/f40 ... sell5=f31/f32；vol×100=股，akshare f32*100 证实）
_BID_BUY_PAIRS = [("f19", "f20"), ("f17", "f18"), ("f15", "f16"),
                  ("f13", "f14"), ("f11", "f12")]    # 买1→买5
_BID_SELL_PAIRS = [("f39", "f40"), ("f37", "f38"), ("f35", "f36"),
                   ("f33", "f34"), ("f31", "f32")]   # 卖1→卖5


def _parse_bids(code: str, data: dict) -> dict:
    """解析 push2 stock/get 五档 data → {code,name,latest,prev_close,buy[],sell[]}。

    buy/sell 每档 {level, price, vol}；vol=raw×100（手→股，akshare 同口径）；
    vol 缺失（'-'）→ None（不臆造 0）。
    """
    def _level(pairs):
        out = []
        for i, (fp, fv) in enumerate(pairs, start=1):
            price = _numf(data.get(fp))
            raw_vol = _numf(data.get(fv))
            vol = (raw_vol * 100) if raw_vol is not None else None
            out.append({"level": i, "price": price, "vol": vol})
        return out
    return {
        "code": str(data.get("f57") or code),
        "name": data.get("f58", ""),
        "latest": _numf(data.get("f43")),
        "prev_close": _numf(data.get("f60")),
        "buy": _level(_BID_BUY_PAIRS),
        "sell": _level(_BID_SELL_PAIRS),
    }


def bids(code: str) -> dict:
    """五档买卖盘（东财 push2/push2delay，走 em_get 限流）。

    push2(实时)易封 → push2delay(延迟行情)优先 + 双 host 降级（同 stock_fund_flow_120d 范式）。
    返回 {code, name, latest, prev_close, buy[5], sell[5]}：每档 {level, price, vol}。
    vol 单位股（raw 手 ×100，与 akshare stock_bid_ask_em 同口径）。
    ⚠️ 不臆造：端点失败/空 data → 空五档（buy/sell=[]，latest/prev_close=None）。
    """
    market_code = 1 if code.startswith("6") else 0
    params = {"fltt": "2", "invt": "2", "fields": _BID_FIELDS,
              "secid": f"{market_code}.{code}"}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        try:
            r = em_get(f"https://{host}/api/qt/stock/get",
                       params=params, headers=headers, timeout=10)
            data = r.json().get("data")
            if data:  # 空数据（None/{}）→ 继续降级下一 host
                return _parse_bids(code, data)
        except Exception:
            continue  # 断连/限流 → 下一 host
    return {"code": code, "name": "", "latest": None,
            "prev_close": None, "buy": [], "sell": []}


def dragon_tiger_board(code: str, trade_date: str | None = None, look_back: int = 30,
                       raise_on_failure: bool = False) -> dict:
    """龙虎榜：该股近期上榜记录 + 最近一次买卖席位 TOP5 + 机构专用席位净买。

    raise_on_failure=True 时，底层 eastmoney_datacenter 源断即 raise（非吞 []），让下游
    get_with_fallback_meta 设 fetch_ok=False（S119 诚实化 risk-trio——源断不再伪装"未上榜 ok"）。
    默认 False = 既有吞行为（向后兼容；risk-trio 调用方传 True，其他调用方 fund_flow/routers/
    first_board_filter 用默认 False 不变，其诚实性未扫、留下一轮 scan 判，YAGNI）。
    """
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)).strftime("%Y-%m-%d")
    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f'(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{trade_date}\')(SECURITY_CODE="{code}")',
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1",
        raise_on_failure=raise_on_failure)
    for r in data:
        records.append({
            "date": str(r.get("TRADE_DATE", ""))[:10],
            "reason": r.get("EXPLANATION", ""),
            "net_buy": round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),  # 万元
            "turnover": round(float(r.get("TURNOVERRATE") or 0), 2),
        })

    seats = {"buy": [], "sell": []}
    institution = {"buy_amt": 0.0, "sell_amt": 0.0, "net_amt": 0.0}
    if records:
        latest = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="BUY", sort_types="-1",
            raise_on_failure=raise_on_failure)
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f'(TRADE_DATE=\'{latest}\')(SECURITY_CODE="{code}")',
            page_size=10, sort_columns="SELL", sort_types="-1",
            raise_on_failure=raise_on_failure)
        for r in buy_data[:5]:
            seats["buy"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                 "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                 "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                 "net": round((r.get("NET") or 0) / 10000, 1)})
        for r in sell_data[:5]:
            seats["sell"].append({"name": r.get("OPERATEDEPT_NAME", ""),
                                  "buy_amt": round((r.get("BUY") or 0) / 10000, 1),
                                  "sell_amt": round((r.get("SELL") or 0) / 10000, 1),
                                  "net": round((r.get("NET") or 0) / 10000, 1)})
        for detail, side in ((buy_data, "buy"), (sell_data, "sell")):
            for r in detail:
                if str(r.get("OPERATEDEPT_CODE", "")) == "0":  # 机构专用席位
                    amt = (r.get("BUY") or 0) if side == "buy" else (r.get("SELL") or 0)
                    institution[f"{side}_amt"] += amt
        institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
        institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
        institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)
    return {"records": records, "seats": seats, "institution": institution}


def lockup_expiry(code: str, trade_date: str | None = None, forward_days: int = 90,
                  raise_on_failure: bool = False) -> dict:
    """限售解禁日历：历史解禁记录 + 未来 N 天待解禁事件。

    字段随东财 2026 改列名同步（a-stock-data §3.6）：旧 LIMITED_STOCK_TYPE/FREE_SHARES_NUM
    已废、致 type/shares 恒空 → 改 FREE_SHARES_TYPE/FREE_SHARES，并补 able_shares（实际可流通股数）。

    S131 R10：``raise_on_failure=True`` 时底层 eastmoney_datacenter 源断即 re-raise
    （非吞成 {"history":[],"upcoming":[]}），让 fetch_share_unlock（event_factors.py）
    据此区分"源断"(→data_status='missing') vs"无解禁"(→data_status='ok')。
    默认 False 向后兼容（既有吞行为，routers/stock_financial:110 → 502 兜底）。
    防封安全：取数路径仍走 em_get 限流/熔断/代理，仅源断时 raise 而非 swallow。
    """
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    history = [{
        "date": str(r.get("FREE_DATE", ""))[:10], "type": r.get("FREE_SHARES_TYPE", ""),
        "shares": r.get("FREE_SHARES", 0), "able_shares": r.get("ABLE_FREE_SHARES", 0),
        "ratio": r.get("FREE_RATIO", 0),
    } for r in eastmoney_datacenter(
        "RPT_LIFT_STAGE", filter_str=f'(SECURITY_CODE="{code}")',
        page_size=15, sort_columns="FREE_DATE", sort_types="-1",
        raise_on_failure=raise_on_failure)]

    end = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
    upcoming = [{
        "date": str(r.get("FREE_DATE", ""))[:10], "type": r.get("FREE_SHARES_TYPE", ""),
        "shares": r.get("FREE_SHARES", 0), "able_shares": r.get("ABLE_FREE_SHARES", 0),
        "ratio": r.get("FREE_RATIO", 0),
    } for r in eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{trade_date}\')(FREE_DATE<=\'{end}\')',
        page_size=20, sort_columns="FREE_DATE", sort_types="1",
        raise_on_failure=raise_on_failure)]
    return {"history": history, "upcoming": upcoming}


def concept_blocks(code: str, raise_on_failure: bool = False) -> dict:
    """个股所属板块/概念归属（东财 slist，行业/概念/地域混合，板块名自解释）。

    S131 R4：``raise_on_failure=True`` 时源断（em_get 断连/限流/JSON 错）即 re-raise
    （非吞成空 dict），让承重 caller 标 degraded/missing（catalyst:53 try/except→"板块未取得"；
    routers/stock_financial:122 try/except→502；topology:86 try/except→空边）。
    默认 False 向后兼容（返空 dict，既有 mock 测试不破）。
    防封安全：取数路径仍走 em_get 限流/熔断/代理，仅源断时 raise 而非 swallow。
    """
    market_code = 1 if code.startswith("6") else 0
    params = {"fltt": "2", "invt": "2", "secid": f"{market_code}.{code}",
              "spt": "3", "pi": "0", "pz": "200", "po": "1", "fields": "f12,f14,f3,f128", "ut": _PUSH2_UT}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        d = em_get("https://push2.eastmoney.com/api/qt/slist/get", params=params, headers=headers, timeout=15).json()
    except Exception:
        # S131 R4：raise_on_failure=True 时 re-raise（源断不伪装合法空 dict），
        # 默认 False 返空 dict（向后兼容）。
        if raise_on_failure:
            raise
        return {"total": 0, "boards": [], "concept_tags": []}
    diff = (d.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = [{"name": it.get("f14", ""), "code": it.get("f12", ""),
               "change_pct": it.get("f3", ""), "lead_stock": it.get("f128", "")} for it in items]
    return {"total": len(boards), "boards": boards, "concept_tags": [b["name"] for b in boards]}


def hot_concepts(code: str) -> list[dict]:
    """个股当下被市场归到哪些概念在炒（东财热门概念命中，按热度降序）。

    S164 R3：走 ``em_get``（method="POST"+json）限流/熔断/代理探测防封
    （原 ``requests.post()`` 裸调 emappdata，绕过防封 backbone 有封 IP 风险）。
    """
    try:
        prefix = "SH" if code.startswith("6") else "SZ"
        r = em_get(
            "https://emappdata.eastmoney.com/stockrank/getHotStockRankList",
            json={"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "srcSecurityCode": prefix + code},
            headers={"User-Agent": UA}, timeout=10, method="POST")
        data = r.json().get("data") or []
    except Exception:
        return []
    return [{"concept": x.get("conceptName"), "bk": x.get("conceptId"), "hit": x.get("hitCount")} for x in data]


def industry_comparison(top_n: int = 20, raise_on_failure: bool = False) -> dict:
    """全行业涨跌幅排名（东财行业板块，~100 个行业）：板块级涨跌 / 涨跌家数 / 领涨。

    S131 R8：``raise_on_failure=True`` 时源断即 re-raise（让 sector_divergence:152
    get_with_fallback_meta / /api/industry 标 data_status='missing'）。默认 False 时
    失败 dict 加 ``data_status='missing'``——/api/industry（stock_financial:158 透传
    整个 dict）可见"源断"非"空排名"，对齐 sector_divergence.py:150-159 范式。
    HTTP 成功但 items 空（真无数据，罕见）返无 data_status 的空 dict（合法空，对齐 S119）。
    默认 False 向后兼容。防封安全：取数路径仍走 em_get 限流/熔断/代理。
    """
    params = {"pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
              "fid": "f3",  # fid=f3 + po=1：按涨跌幅降序，否则 top/bottom 切片非涨幅序（a-stock-data §3.7）
              "fs": "m:90+t:2", "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207", "ut": _PUSH2_UT}
    try:
        d = em_get("https://push2.eastmoney.com/api/qt/clist/get",
                   params=params, headers={"User-Agent": UA}, timeout=15).json()
    except Exception:
        # S131 R8：raise_on_failure=True 时 re-raise；默认 False 返空 dict +
        # data_status='missing'（/api/industry 透传可见源断，非伪装空排名）。
        if raise_on_failure:
            raise
        return {"top": [], "bottom": [], "total": 0, "data_status": "missing"}
    items = d.get("data", {}).get("diff", [])
    if isinstance(items, dict):
        items = list(items.values())
    if not items:
        return {"top": [], "bottom": [], "total": 0}
    rows = [{
        "rank": i + 1, "name": it.get("f14", ""), "change_pct": it.get("f3", 0),
        "code": it.get("f12", ""), "up_count": it.get("f104", 0), "down_count": it.get("f105", 0),
    } for i, it in enumerate(items)]
    return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}
