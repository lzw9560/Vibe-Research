# -*- coding: utf-8 -*-
"""配置管理 —— 默认配置 + 用户配置覆盖。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssistantDefaultConfig:
    """投研助手默认配置。"""

    # === 基因选股 ===
    GENE_LOOKBACK_DAYS: int = 250
    GENE_QUALIFY_THRESHOLD: float = 60.0
    GENE_HIGH_THRESHOLD: float = 75.0
    GENE_FACTORS_WEIGHT: dict[str, float] = field(
        default_factory=lambda: {
            "premium": 0.25,
            "red_plate": 0.25,
            "seal": 0.25,
            "open_premium": 0.15,
            "activity": 0.10,
        }
    )

    # === STI情绪 ===
    STI_WEIGHTS: dict[str, float] = field(
        default_factory=lambda: {
            "seal_rate": 0.25,
            "limit_up_count": 0.15,
            "up_down_ratio": 0.12,
            "prev_zt_performance": 0.12,
            "avg_premium": 0.10,
            "board_height": 0.10,
            "north_flow": 0.08,
            "turnover": 0.08,
        }
    )
    STI_PERCENTILE_WINDOW: int = 252

    # === 推荐引擎 ===
    RECOMMEND_HIGH_THRESHOLD: float = 60.0
    RECOMMEND_MEDIUM_THRESHOLD: float = 50.0
    RECOMMEND_INDUSTRY_PERCENTILE_MIN: float = 80.0

    # === 竞价监控 ===
    AUCTION_OPEN_RANGE: tuple[float, float] = (0.0, 0.06)
    AUCTION_VOLUME_RATIO_MIN: float = 3.0
    AUCTION_CANCEL_RATE_MAX: float = 0.25
    AUCTION_SAMPLE_INTERVAL: int = 30

    # === ML过滤（未来实验方向，当前默认关闭） ===
    AI_CONFIDENCE_THRESHOLD: float = 0.60
    AI_RETRAIN_DAYS: int = 1
    AI_OOS_THRESHOLD: float = 0.6
    AI_AUTO_ROLLBACK_DAYS: int = 5

    # === 推送 ===
    PUSH_CHANNELS: list[str] = field(default_factory=lambda: ["feishu"])
    PUSH_THROTTLE: dict[str, Any] = field(
        default_factory=lambda: {
            "same_ticker_interval_sec": 300,
            "max_daily_per_ticker": 3,
            "max_daily_total": 20,
        }
    )

    # === 回测 ===
    BACKTEST_INITIAL_CAPITAL: float = 1_000_000.0
    BACKTEST_LOOKBACK_DAYS: int = 250

    # === 性能 ===
    CONCURRENT_REQUESTS: int = 10
    BATCH_SIZE: int = 100
    CACHE_TTL_HOURS: int = 12

    # === 数据库 ===
    DB_PATH: str = "vibe_research.db"

    # === 风险 ===
    RISK_DYNAMIC_THRESHOLDS: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            "HIGH潮": {"high": 75, "medium": 50, "low": 25},
            "START": {"high": 70, "medium": 45, "low": 20},
            "DIVERGENCE": {"high": 65, "medium": 40, "low": 15},
            "FREEZE": {"high": 60, "medium": 35, "low": 10},
            "DECLINE": {"high": 55, "medium": 30, "low": 5},
        }
    )

    # === 推送 ===
    PUSH_QUIET_HOURS: tuple[int, int] = (22, 7)


@dataclass
class AssistantUserConfig:
    """用户可覆盖的配置（.env / 前端设置）。"""

    gene_qualify_threshold: float | None = None
    gene_high_threshold: float | None = None
    hard_stop_loss: float | None = None
    ai_confidence_threshold: float | None = None
    feishu_webhook: str | None = None

    def resolve(self, defaults: AssistantDefaultConfig) -> dict[str, Any]:
        """合并默认配置和用户配置。"""
        config: dict[str, Any] = {}
        for key, default_val in vars(defaults).items():
            user_val = getattr(self, key, None)
            config[key] = user_val if user_val is not None else default_val
        return config


def load_config() -> AssistantDefaultConfig:
    """从环境变量加载配置覆盖。"""
    cfg = AssistantDefaultConfig()

    # 基因阈值
    if os.getenv("VR_GENE_QUALIFY_THRESHOLD"):
        cfg.GENE_QUALIFY_THRESHOLD = float(os.getenv("VR_GENE_QUALIFY_THRESHOLD"))
    if os.getenv("VR_GENE_HIGH_THRESHOLD"):
        cfg.GENE_HIGH_THRESHOLD = float(os.getenv("VR_GENE_HIGH_THRESHOLD"))

    # 推荐阈值
    if os.getenv("VR_RECOMMEND_HIGH_THRESHOLD"):
        cfg.RECOMMEND_HIGH_THRESHOLD = float(os.getenv("VR_RECOMMEND_HIGH_THRESHOLD"))
    if os.getenv("VR_RECOMMEND_MEDIUM_THRESHOLD"):
        cfg.RECOMMEND_MEDIUM_THRESHOLD = float(os.getenv("VR_RECOMMEND_MEDIUM_THRESHOLD"))

    # 推送
    if os.getenv("VR_FEISHU_WEBHOOK"):
        cfg.PUSH_CHANNELS = ["feishu"]

    # 性能
    if os.getenv("VR_CONCURRENT_REQUESTS"):
        cfg.CONCURRENT_REQUESTS = int(os.getenv("VR_CONCURRENT_REQUESTS"))
    if os.getenv("VR_BATCH_SIZE"):
        cfg.BATCH_SIZE = int(os.getenv("VR_BATCH_SIZE"))

    return cfg


# 全局配置单例
default_config = load_config()
