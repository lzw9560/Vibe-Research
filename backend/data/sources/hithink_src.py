# -*- coding: utf-8 -*-
"""S104：hithink-finance CLI 数据源封装。

作 A 股结构性缺口唯一源——补东财/新浪/腾讯零供给的字段：
- 估值 PS_TTM / PCF_TTM（东财 full_valuation 结构性缺）
- 异动 / 飙升榜 / 热股榜（项目从无独立源）

**集成形态**：node CLI subprocess（hithink-finance v0.1.7，非 Python 库）。
按需调用，冷启动 ~1s（低频按需源可接受，非批量回测路径）。

**硬约束**（grill 锁定）：
1. thscode 映射：复用 ``data.sources.tencent.get_prefix``（6 位 → sh/sz/bj），
   转 hithink 的 ``.SH/.SZ/.BJ`` 后缀。返回时剥后缀还原裸 6 位 code（项目内部体系）。
2. ok 字段解析：hithink 错误是 JSON envelope ``{"ok":false,"error":{...}}``，
   subprocess 退出码恒 0。封装必须解析 ok，ok:false 当失败返项目惯用空（dict/list），
   **不透传 error envelope**（否则下游拿 error 当数据崩）。
3. subprocess 硬超时（估值 15s / 特色数据 30s）。
4. 熔断：``circuit_breaker.get_breaker("hithink")``（远端也会断）。
5. 大结果超阈值（>1000 行）落盘临时文件（``.vibe-research/``，私有数据隔离底线）。

**§44 口径**：PS/PCF 是东财零供给的唯一源，无需 cross_validate 仲裁；
PE/PB 两源一致但不在本 spec 接仲裁（等 cross_validate 接线，第 3 层孤儿）。
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from circuit_breaker import get_breaker
from data.sources.tencent import get_prefix

logger = logging.getLogger("vibe-research")

_CLI = "hithink-finance"
_VALUATION_TIMEOUT = 15
_SPECIAL_TIMEOUT = 30
_LARGE_THRESHOLD = 1000  # 超过 1000 行落盘

# 估值快照 5min TTL 缓存（盘中估值不变，省 subprocess 冷启动）
_valuation_cache: dict[tuple[str, ...], tuple[float, dict[str, dict]]] = {}
_VALUATION_CACHE_TTL = 300.0


def _to_thscode(code: str) -> str:
    """6 位裸 code → hithink thscode（带交易所后缀）。

    复用 tencent.get_prefix（6/9/5 开头→SH，8 开头→BJ，其余→SZ）。
    例：600519 → 600519.SH，000001 → 000001.SZ，830xxx → 830xxx.BJ。
    """
    return f"{code}.{get_prefix(code).upper()}"


def _strip_thscode(thscode: str) -> str:
    """thscode（600519.SH）→ 裸 6 位 code（600519）。无后缀原样返。"""
    return thscode.split(".")[0]


def _run_cli(args: list[str], timeout: int, large: bool = False) -> dict[str, Any] | None:
    """调 hithink-finance CLI，返解析后的 data 字段（剥 envelope）。

    ok:false / 超时 / 熔断 → 返 None（调用方降级为空结构，不透传 error envelope）。
    大结果（large=True）走 --output 落盘临时文件再读。
    """
    breaker = get_breaker("hithink")
    if not breaker.allow_request():
        logger.warning("[hithink] 熔断中，快速失败 args=%s", args[:3])
        return None

    cmd = [_CLI, *args, "--format", "json"]
    output_path: Path | None = None
    if large:
        # 落盘临时文件（私有数据隔离：.vibe-research/ 下）
        from vr_paths import resolve_data_dir
        output_path = resolve_data_dir() / "hithink_cache" / f"{int(time.time() * 1000)}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["--output", str(output_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        breaker.record_success()
        if proc.returncode != 0:
            logger.warning("[hithink] CLI 非零退出 code=%s stderr=%s", proc.returncode, proc.stderr[:200])
            return None
        # 大结果从落盘文件读
        if output_path and output_path.exists():
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            finally:
                try:
                    output_path.unlink()
                except OSError:
                    pass
        else:
            payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        if not payload.get("ok"):
            err = payload.get("error", {})
            logger.warning("[hithink] ok=false args=%s err=%s", args[:3], str(err)[:150])
            return None
        return payload.get("data") or {}
    except subprocess.TimeoutExpired:
        breaker.record_failure()
        logger.warning("[hithink] 超时 args=%s timeout=%ss", args[:3], timeout)
        return None
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        breaker.record_failure()
        logger.warning("[hithink] 调用失败 args=%s %s: %s", args[:3], type(e).__name__, str(e)[:120])
        return None


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """hithink data → item 列表。data 可能是 {item:[...]} 或 {items:[...]} 或裸 list。"""
    if isinstance(data, dict):
        return data.get("item") or data.get("items") or []
    if isinstance(data, list):
        return data
    return []


def valuation_snapshot(codes: list[str]) -> dict[str, dict]:
    """批量估值快照——补东财结构性缺的 PS_TTM / PCF_TTM。

    返 {裸code: {pe_ttm, pe_mrq, pb_mrq, ps_ttm, pcf_ttm}}。
    hithink 失败/熔断 → 返 {}（调用方降级，PS/PCF 仍 None，诚实缺失）。
    5min TTL 缓存（盘中估值不变，省 subprocess 冷启动 ~1s）。
    """
    if not codes:
        return {}
    # 缓存键：排序后的 codes 元组（防顺序差异 miss）
    cache_key = tuple(sorted(codes))
    now = time.time()
    cached = _valuation_cache.get(cache_key)
    if cached and now - cached[0] < _VALUATION_CACHE_TTL:
        return cached[1]

    thscodes = ",".join(_to_thscode(c) for c in codes)
    data = _run_cli(["valuation", "snapshot", "--thscodes", thscodes], _VALUATION_TIMEOUT)
    if data is None:
        return {}
    out: dict[str, dict] = {}
    for it in _items(data):
        ths = it.get("thscode") or it.get("code") or ""
        bare = _strip_thscode(ths)
        if not bare:
            continue
        out[bare] = {
            "pe_ttm": it.get("pe_ttm"),
            "pe_mrq": it.get("pe_mrq"),
            "pb_mrq": it.get("pb_mrq"),
            "ps_ttm": it.get("ps_ttm"),
            "pcf_ttm": it.get("pcf_ttm"),
        }
    if out:
        _valuation_cache[cache_key] = (now, out)
    return out


def skyrocket(period: str = "day") -> list[dict]:
    """飙升榜。返 [{code, name, rank, heat, rank_change, rank_trend}]。

    period: hithink 只接受 day / hour（非 daily）。
    """
    data = _run_cli(["special", "skyrocket", "--period", period], _SPECIAL_TIMEOUT)
    if data is None:
        return []
    return _normalize_rank_items(_items(data))


def hot_stock(period: str = "day") -> list[dict]:
    """热股榜。返同飙升榜结构。period: day / hour。"""
    data = _run_cli(["special", "hot-stock", "--period", period], _SPECIAL_TIMEOUT)
    if data is None:
        return []
    return _normalize_rank_items(_items(data))


def anomaly_list(tag_codes: str | None = None) -> list[dict]:
    """今日异动分析。返 [{code, name, ...}]。

    实测盘后 item=0（盘后异动本就少），诚实返空。
    """
    args = ["special", "anomaly-list"]
    if tag_codes:
        args += ["--tag-codes", tag_codes]
    data = _run_cli(args, _SPECIAL_TIMEOUT, large=True)  # 异动可能全市场，落盘
    if data is None:
        return []
    return _normalize_anomaly_items(_items(data))


def anomaly_stock(codes: list[str]) -> list[dict]:
    """个股异动（≤50 只 thscodes）。返 [{code, name, ...}]。"""
    if not codes or len(codes) > 50:
        return []
    thscodes = ",".join(_to_thscode(c) for c in codes)
    data = _run_cli(["special", "anomaly-stock", "--thscodes", thscodes], _SPECIAL_TIMEOUT)
    if data is None:
        return []
    return _normalize_anomaly_items(_items(data))


def _normalize_rank_items(items: list[dict[str, Any]]) -> list[dict]:
    """飙升/热股榜 item 归一：thscode→code，保留 rank/heat/rank_change/rank_trend。"""
    out = []
    for it in items:
        ths = it.get("thscode") or it.get("code") or ""
        bare = _strip_thscode(ths)
        if not bare:
            continue
        out.append({
            "code": bare,
            "name": it.get("name", ""),
            "rank": it.get("rank"),
            "heat": it.get("heat"),
            "rank_change": it.get("rank_change"),
            "rank_trend": it.get("rank_trend"),
        })
    return out


def _normalize_anomaly_items(items: list[dict[str, Any]]) -> list[dict]:
    """异动 item 归一：thscode→code，原样保留 hithink 字段（异动 schema 未实测全字段）。"""
    out = []
    for it in items:
        ths = it.get("thscode") or it.get("code") or ""
        bare = _strip_thscode(ths)
        if not bare:
            continue
        row = {"code": bare, "name": it.get("name", "")}
        # 原样透传其余字段（异动字段未实测全，不臆造归一）
        for k, v in it.items():
            if k not in ("thscode", "ticker", "name"):
                row[k] = v
        out.append(row)
    return out
