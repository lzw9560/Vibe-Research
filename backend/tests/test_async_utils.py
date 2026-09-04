# -*- coding: utf-8 -*-
"""C3 缓解回归：utils.async_utils.run_coro_sync 避嵌套 event loop。

quant-mindset C3 裂缝登记：asyncio.run 不能在 running loop 里调（嵌套崩，
RuntimeError: asyncio.run() cannot be called from a running event loop）。
run_coro_sync 须检测 running loop：有则线程兜底（新线程起新 loop），无则直接 asyncio.run。
本测锁住守卫——若被删/改坏，async 上下文分支会抛 RuntimeError。
"""

import pytest

from utils.async_utils import run_coro_sync


async def _coro_returning(value):
    """简单 coro：yield 一次后返值（验证 run_coro_sync 正确跑完 coro，不丢结果）。"""
    import asyncio
    await asyncio.sleep(0)
    return value


def test_run_coro_sync_in_sync_context_direct_run():
    """sync 上下文（无 running loop）→ 直接 asyncio.run，返结果。"""
    # pytest sync 测试 fn 无 running loop
    assert run_coro_sync(_coro_returning(42)) == 42


def test_run_coro_sync_in_async_context_threads_no_nested_crash():
    """async 上下文（有 running loop）→ 须线程兜底，不嵌套 loop 崩（C3 回归守卫）。

    若 run_coro_sync 守卫被删（直接 asyncio.run），async 上下文里会抛
    'asyncio.run() cannot be called from a running event loop'。本测断言不抛 + 返值。
    """
    import asyncio

    async def _caller_inside_running_loop():
        # 此时 running loop 存在；run_coro_sync 须走线程兜底
        return run_coro_sync(_coro_returning(99))

    # asyncio.run 建外层 loop；_caller 在其内执行 → run_coro_sync 见 running loop → 线程兜底
    assert asyncio.run(_caller_inside_running_loop()) == 99


def test_run_coro_sync_propagates_exception():
    """coro 抛异常 → run_coro_sync 传播（不吞），sync 上下文亦如此。"""
    async def _boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_coro_sync(_boom())


def test_run_coro_sync_thread_fallback_propagates_exception():
    """thread-fallback 路径（async 上下文）异常也须传播，不被 ThreadPoolExecutor 吞。

    S148 审计补测：run_coro_sync 在有 running loop 时走 ThreadPoolExecutor.submit(
    asyncio.run).result()——.result() 重抛子线程异常。原 exception 测只在 sync 上下文
    （直 asyncio.run 路径），未覆盖 thread-fallback；若有人误包 try 吞 .result() 异常，
    原测不报。本测在 async caller 内抛，锁住 thread-fallback 异常传播。
    """
    import asyncio

    async def _boom():
        raise ValueError("boom-thread")

    async def _caller_inside_running_loop():
        # running loop 存在 → run_coro_sync 走线程兜底；_boom 在子线程抛 ValueError
        return run_coro_sync(_boom())

    # 外层 asyncio.run 建 loop；_caller 在其内执行；thread-fallback 的 .result() 须重抛
    with pytest.raises(ValueError, match="boom-thread"):
        asyncio.run(_caller_inside_running_loop())
