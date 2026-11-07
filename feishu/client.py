# -*- coding: utf-8 -*-
"""飞书 Bot 客户端 — send_feishu + ping_healthchecks + tenacity 重试。

从 feishu_daily_push.py 拆出。改进：
- send_feishu 失败重试 3 次（指数退避 1s/2s/4s），用 tenacity
- tenacity 不可用时降级为内置 _retry（同等语义，不破坏无 tenacity 的生产环境）
- print 全部替换为 logging
- ping_healthchecks 保留（orchestrator 已加，这里沿用）
"""
from __future__ import annotations

import json
import logging
import os
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ─── 配置：从 .env 加载 ───
def _load_env() -> None:
    """从 .env 加载环境变量（兼容 feishu_daily_push.py 原逻辑）。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()

WEBHOOK = os.getenv("FEISHU_WEBHOOK_URL", "")
HEALTHCHECKS_URL = os.getenv("VR_HEALTHCHECKS_URL", "")

# ─── 重试机制：优先用 tenacity，降级为内置实现 ───
# 先声明为 Any，避免 try/except ImportError 让类型检查器报 "possibly unbound"
_tenacity_retry: Callable[..., Any]
stop_after_attempt: Callable[..., Any]
wait_exponential: Callable[..., Any]
retry_if_exception_type: Callable[..., Any]
before_sleep_log: Callable[..., Any]
try:
    from tenacity import (  # type: ignore[import]
        retry as _tenacity_retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception_type,
        before_sleep_log,
    )
    _HAS_TENACITY = True
except ImportError:
    _HAS_TENACITY = False


class FeishuSendError(Exception):
    """飞书发送失败（网络层或飞书返回非零）。"""


def _builtin_retry(
    max_attempts: int = 3,
    waits: tuple[float, ...] = (1.0, 2.0, 4.0),
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """tenacity 不可用时的等价重试：max_attempts 次，等待 waits 序列。

    tenacity 版语义：stop_after_attempt(3) + wait_exponential。
    为对齐 spec 的 1s/2s/4s，此处 waits 显式给定。
    """
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt >= max_attempts:
                        logger.error(
                            "%s 第%d/%d次失败，放弃: %s",
                            fn.__name__, attempt, max_attempts, e,
                        )
                        raise
                    wait = waits[min(attempt - 1, len(waits) - 1)]
                    logger.warning(
                        "%s 第%d/%d次失败，%ss后重试: %s",
                        fn.__name__, attempt, max_attempts, wait, e,
                    )
                    time.sleep(wait)
            # unreachable，类型检查兜底
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("unreachable")
        return wrapper
    return deco


# send_feishu 的网络异常类型（重试只针对网络瞬态失败）
_NETWORK_EXC: tuple[type[BaseException], ...] = (
    OSError,            # 含 socket/timeout/连接拒绝（urllib 抛 URLError ⊂ OSError）
    TimeoutError,
    ConnectionError,
)


def _build_send_retry() -> Callable[[Callable[..., T]], Callable[..., T]]:
    """构建 send_feishu 的重试装饰器：优先 tenacity，否则内置。"""
    if _HAS_TENACITY:
        # 类型检查器无法推断 try/except ImportError 绑定，运行时 _HAS_TENACITY
        # 为 True 时这些名称一定已绑定，此处 noqa 抑制误报。
        return _tenacity_retry(  # type: ignore[return-value]
            stop=stop_after_attempt(3),  # noqa: F821
            wait=wait_exponential(multiplier=1, base=2, max=4),  # noqa: F821
            retry=retry_if_exception_type(_NETWORK_EXC),  # noqa: F821
            reraise=True,
            before_sleep=before_sleep_log(logger, logging.WARNING),  # noqa: F821
        )
    return _builtin_retry(
        max_attempts=3, waits=(1.0, 2.0, 4.0), exceptions=_NETWORK_EXC,
    )


_send_retry = _build_send_retry()


def ping_healthchecks(success: bool, mode: str) -> None:
    """推送结果 ping healthchecks.io（成功 ping /endpoint，失败 ping /endpoint/fail）。

    失败静默——healthchecks 不影响主流程。
    """
    if not HEALTHCHECKS_URL:
        return
    import urllib.request
    url = HEALTHCHECKS_URL.rstrip("/") + ("/" if success else "/fail")
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=5)
    except Exception as e:
        logger.debug("healthchecks ping 失败（忽略）: %s", e)


def _do_send(card: dict, mode: str) -> bool:
    """单次发送（不含重试）。网络异常向上抛给重试装饰器；飞书返回非零返回 False。"""
    import urllib.request

    payload = json.dumps({"msg_type": "interactive", "card": card}).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    ok = result.get("code") == 0 or result.get("StatusCode") == 0
    if not ok:
        logger.error("飞书返回非零: %s", result)
    return ok


@_send_retry
def send_feishu(card: dict, mode: str = "") -> bool:
    """发送飞书卡片消息。

    失败时重试 3 次（指数退避 1s/2s/4s，仅网络异常重试），
    重试耗尽或飞书返回非零记日志 + ping healthchecks。

    Args:
        card: 飞书卡片 dict
        mode: 推送模式（premarket/intraday/...），用于 healthchecks 区分

    Returns:
        True 成功，False 失败（含飞书返回非零、网络重试耗尽）
    """
    if not WEBHOOK:
        logger.error("FEISHU_WEBHOOK_URL 未设置")
        ping_healthchecks(False, mode)
        return False
    try:
        ok = _do_send(card, mode)
    except _NETWORK_EXC as e:
        # 重试耗尽后（tenacity reraise=True / 内置 reraise）抛到这里
        logger.error("发送失败（重试耗尽）: %s", e)
        ping_healthchecks(False, mode)
        return False
    except Exception as e:
        # 非网络异常（JSON 解析等）不重试
        logger.error("发送异常（非网络，不重试）: %s", e)
        ping_healthchecks(False, mode)
        return False

    if ok:
        ping_healthchecks(True, mode)
        logger.info("飞书推送成功 (mode=%s)", mode)
    else:
        ping_healthchecks(False, mode)
    return ok
