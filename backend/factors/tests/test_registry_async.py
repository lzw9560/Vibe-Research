"""S026: registry.afetch_all 异步并行采集单测。"""
from __future__ import annotations

import asyncio

from factors import registry
from factors.base import FactorResult


class _FakeFactor:
    """记录 fetch 调用的假因子。"""

    def __init__(self, fid: str, recorder: list):
        self.factor_id = fid
        self.factor_name = fid
        self._recorder = recorder

    def fetch(self, date: str, config: dict | None = None) -> FactorResult:
        self._recorder.append((self.factor_id, date))
        return FactorResult(
            factor_id=self.factor_id,
            factor_name=self.factor_name,
            candidates=[],
            layers=[],
            config={},
        )


def test_afetch_all_parallel_and_offloaded(monkeypatch):
    # Arrange
    recorder: list = []
    f1 = _FakeFactor("f1", recorder)
    f2 = _FakeFactor("f2", recorder)
    monkeypatch.setattr(registry, "_registry", {"f1": f1, "f2": f2})
    to_thread_calls: list = []
    orig_to_thread = asyncio.to_thread

    async def spy_to_thread(fn, *args, **kwargs):
        to_thread_calls.append(fn)
        return await orig_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(registry.asyncio, "to_thread", spy_to_thread)

    # Act
    results = asyncio.run(registry.afetch_all("2026-08-03"))

    # Assert: 顺序对齐 registry；每个 factor.fetch offload 到线程（释放事件循环）
    assert [r.factor_id for r in results] == ["f1", "f2"]
    assert len(to_thread_calls) == 2
    assert ("f1", "2026-08-03") in recorder
    assert ("f2", "2026-08-03") in recorder


def test_afetch_all_empty_registry_returns_empty(monkeypatch):
    monkeypatch.setattr(registry, "_registry", {})
    results = asyncio.run(registry.afetch_all("2026-08-03"))
    assert results == []
