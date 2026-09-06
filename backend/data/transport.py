# -*- coding: utf-8 -*-
"""S008 数据层 — 东财传输层（限流/熔断/代理探测收口）。

抽自 ``astock.em_get``（astock.py:487）。三职责合一：
- **限流**：``_EM_MIN_INTERVAL`` 保证两次东财请求最小间隔（内置防封节流）+ 抖动。
- **熔断**：``circuit_breaker.get_breaker(breaker_name)`` —— S164 R2 拆 2 组：
  ``eastmoney``（push2/push2his/push2ex/fflow，IP+ut 敏感）/ ``eastmoney_datacenter``
  （datacenter-web，不需 ut）。5 次失败 OPEN / 60s 恢复 / half-open。push2his 封禁
  不连累 datacenter。
- **代理探测**：``auto`` 模式先直连（``trust_env=False``、短超时不重试），成功固定 ``direct``；
  失败降级系统代理（带瞬态错误退避重试）并固定 ``proxy``。探测结果整进程复用。
  ``VR_DATA_PROXY=1`` 跳过探测、强制走代理。

语义与原 ``astock.em_get`` 完全一致，只是换了文件组织。``astock.em_get`` 改为薄封装
调本模块，28 个消费者无需改动。
"""

from __future__ import annotations

import os
import random
import threading
import time

from circuit_breaker import get_breaker

# 东财请求最小间隔（秒），内置防封节流
_EM_MIN_INTERVAL = 0.3


def _select_breaker_name(url: str) -> str:
    """S164 R2：按 URL host 选 eastmoney breaker 分组。

    东财端点拆 2 组（避免 push2his 封禁连累 datacenter）：
    - ``eastmoney``（push2/push2his/push2ex/push2delay/np-anotice/searchapi）：
      IP+ut 敏感，同 host family。fflow 是 push2his 上的 path（非独立子域）。
    - ``eastmoney_datacenter``（datacenter-web）：不需 ut，不同子域。

    其余非东财源（ths/sina_kline/sina_financial/worldmonitor/hithink）已有独立 breaker，
    不在此函数 scope 内。
    """
    if "datacenter" in url:
        return "eastmoney_datacenter"
    return "eastmoney"
_em_last_call = [0.0]           # 上次请求时间戳（可变单元素列表，模块级共享）
_em_last_call_lock = threading.Lock()  # L1 修复：保护 _em_last_call 读写
_EM_SESSIONS: dict = {}         # {direct(bool): requests.Session}
_em_mode_lock = threading.Lock()  # L1 修复：保护 _em_mode 读写
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 数据层连接模式：国内财经站本应「直连」——科学上网系统代理会把东财这类国内站路由挂掉。
# auto：先试直连、失败再降级走系统代理；探测一次后固定，避免每次重试。
# VR_DATA_PROXY=1 强制走代理（少数「必须靠代理才能出网」的环境）。
_em_mode = ["proxy" if os.environ.get("VR_DATA_PROXY", "").strip().lower() in ("1", "true", "yes") else "auto"]


def _em_session(direct: bool):
    """东财专用会话。direct=True → trust_env=False 忽略代理环境变量、直连。

    直连会话不重试（探测要快，失败即降级）；代理会话保留瞬态错误退避重试。惰性构建、复用。
    """
    if direct in _EM_SESSIONS:
        return _EM_SESSIONS[direct]
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": _UA})
    s.trust_env = not direct  # 直连会话不读环境里的代理配置
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry = Retry(total=0) if direct else Retry(
            total=3, connect=3, backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    except Exception:
        pass  # 老版本 urllib3 缺参数时降级为无重试
    _EM_SESSIONS[direct] = s
    return s


def eastmoney_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 15):
    """东财统一请求入口：串行限流 + 直连优先、失败降级系统代理。

    第一次请求探测：先直连（短超时、不重试），成功即固定走直连；失败则降级走系统代理并固定。
    探测结果整个进程复用，避免每次重试。``VR_DATA_PROXY=1`` 可跳过探测、强制走代理。
    """
    breaker_name = _select_breaker_name(url)
    breaker = get_breaker(breaker_name)
    if not breaker.allow_request():
        raise RuntimeError(f"[CircuitBreaker:{breaker_name}] 东财数据源熔断中，快速失败（{url}）")

    # L1 修复：限流时间戳加锁，防并发探测浪费
    with _em_last_call_lock:
        wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        with _em_mode_lock:
            mode = _em_mode[0]
        if mode != "auto":
            r = _em_session(mode == "direct").get(url, params=params, headers=headers, timeout=timeout)
            breaker.record_success()
            return r
        # auto：先直连，成功固定 direct；直连失败再走系统代理、成功固定 proxy。
        try:
            r = _em_session(True).get(url, params=params, headers=headers, timeout=min(timeout, 8))
            with _em_mode_lock:
                _em_mode[0] = "direct"
            breaker.record_success()
            return r
        except Exception:
            r = _em_session(False).get(url, params=params, headers=headers, timeout=timeout)
            with _em_mode_lock:
                _em_mode[0] = "proxy"
            breaker.record_success()
            return r
    except Exception:
        breaker.record_failure()
        raise
    finally:
        # L3 修复：成功/失败都更新时间戳（保持限流间隔，防失败后立即重试触发限流）
        with _em_last_call_lock:
            _em_last_call[0] = time.time()
