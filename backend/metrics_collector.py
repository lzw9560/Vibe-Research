"""性能指标采集器 —— 内存滚动窗口，零第三方依赖。"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MetricSample:
    """单次采样。"""
    duration: float = 0.0
    endpoint: str = ""
    tier: str = ""
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """线程安全的性能指标采集器。"""

    def __init__(self, max_samples: int = 1024):
        self._lock = threading.Lock()
        self._samples: deque[MetricSample] = deque(maxlen=max_samples)
        self._tier_samples: Dict[str, deque[MetricSample]] = {
            "data_fetch": deque(maxlen=max_samples),
            "compute": deque(maxlen=max_samples),
            "api_response": deque(maxlen=max_samples),
        }

    def record(self, duration: float, endpoint: str, tier: str = "api_response") -> None:
        """记录一次耗时采样。"""
        sample = MetricSample(duration=duration, endpoint=endpoint, tier=tier)
        with self._lock:
            self._samples.append(sample)
            if tier in self._tier_samples:
                self._tier_samples[tier].append(sample)

    def _stats(self, samples: deque[MetricSample]) -> Dict[str, Any]:
        """计算统计量。"""
        if not samples:
            return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
        durations = [s.duration for s in samples]
        durations_sorted = sorted(durations)
        n = len(durations_sorted)
        return {
            "count": n,
            "avg": round(sum(durations) / n, 3),
            "p50": round(durations_sorted[int(n * 0.50)], 3),
            "p95": round(durations_sorted[int(n * 0.95)], 3),
            "p99": round(durations_sorted[int(n * 0.99)], 3),
            "max": round(max(durations), 3),
        }

    def get_tier_stats(self, tier: str) -> Dict[str, Any]:
        """获取指定层的统计。"""
        with self._lock:
            return self._stats(self._tier_samples.get(tier, deque()))

    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有层的统计。"""
        with self._lock:
            return {
                "data_fetch": self._stats(self._tier_samples["data_fetch"]),
                "compute": self._stats(self._tier_samples["compute"]),
                "api_response": self._stats(self._tier_samples["api_response"]),
                "total": self._stats(self._samples),
            }

    def get_recent_samples(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近采样。"""
        with self._lock:
            return [
                {
                    "duration": s.duration,
                    "endpoint": s.endpoint,
                    "tier": s.tier,
                    "timestamp": s.timestamp,
                }
                for s in list(self._samples)[-limit:]
            ]


# 全局单例
collector = MetricsCollector()
