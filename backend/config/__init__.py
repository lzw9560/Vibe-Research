# -*- coding: utf-8 -*-
"""配置管理 —— 默认配置 + 用户配置覆盖。

S015 R1：通知相关 30+ 配置项已拆到 ``config.notification``；本模块经
dataclass 继承将 ``NotificationConfig`` 合并进 ``AssistantDefaultConfig``，
并 re-export 通知符号，保持向后兼容：
- ``from config import default_config`` ✅
- ``from config import AssistantDefaultConfig`` ✅（通知字段经继承可访问）
- ``import config; config._parse_bool`` ✅

原顶层 ``config.py`` 已由本包（``config/__init__.py``）取代。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from config.notification import (  # noqa: F401  (re-export)
    NotificationConfig,
    NOTIFICATION_ENV_MAP,
    apply_notification_env,
)

_log = logging.getLogger("vibe-research.config")

# 自动加载 .env 文件。本文件位于 backend/config/__init__.py，需上溯一层到 backend/。
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))


def _parse_bool(key: str, value: str | None, default: bool) -> bool:
    """环境变量 bool 解析：非法值告警（不静默吞），返回 default。"""
    if value is None:
        return default
    v = value.strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off"):
        return False
    _log.warning("无效 bool 配置 %s=%r（期望 true/false/1/0/yes/no），用默认 %s", key, value, default)
    return default


def _parse_int(key: str, value: str | None, default: int) -> int:
    """环境变量 int 解析：非法值告警（不静默吞），返回 default。"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        _log.warning("无效 int 配置 %s=%r，用默认 %s", key, value, default)
        return default


def _parse_float(key: str, value: str | None, default: float) -> float:
    """环境变量 float 解析：非法值告警（不静默吞），返回 default。"""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        _log.warning("无效 float 配置 %s=%r，用默认 %s", key, value, default)
        return default


@dataclass
class AssistantDefaultConfig(NotificationConfig):
    """投研助手默认配置。

    通知/推送字段经继承自 ``NotificationConfig``（S015 R1 拆分）；其余域
    （基因选股 / STI 情绪 / 推荐引擎 / 竞价监控 / 候选池漏斗 / ML / 回测 /
    性能 / 数据库 / 风险）定义在本类。
    """

    # === 基因选股 ===
    GENE_LOOKBACK_DAYS: int = 252
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
            "limit_up_count": 0.15,
            "limit_down_count": 0.13,
            "seal_rate": 0.25,
            "advance_decline_ratio": 0.10,
            "promotion_rate": 0.22,
            "prev_zt_performance": 0.10,
            "max_boards": 0.05,
        }
    )
    STI_PERCENTILE_WINDOW: int = 252

    # === 推荐引擎 ===
    RECOMMEND_HIGH_THRESHOLD: float = 60.0
    RECOMMEND_MEDIUM_THRESHOLD: float = 50.0
    # 行业分位数过滤阈值（当前未使用，预留）
    RECOMMEND_INDUSTRY_PERCENTILE_MIN: float = 80.0

    # === 竞价监控 ===
    AUCTION_OPEN_RANGE: tuple[float, float] = (0.0, 0.06)
    AUCTION_VOLUME_RATIO_MIN: float = 3.0
    AUCTION_CANCEL_RATE_MAX: float = 0.25
    AUCTION_SAMPLE_INTERVAL: int = 30
    AUCTION_CHANNEL_LATENCY_MS: dict[str, int] = field(
        default_factory=lambda: {
            "call_auction": 50,
            "continuous_trading": 20,
        }
    )

    # === 候选池漏斗 + 诊断卡（S002 P1）===
    CANDIDATE_FUNNEL_MODE: str = "suggest"  # auto/suggest/manual
    CANDIDATE_FUNNEL_BASE: dict[str, float] = field(
        default_factory=lambda: {
            "turnover_cold": 8.0,
            "turnover_hot": 20.0,
            "vol_ratio_active": 2.0,
            "amount_yi_min": 10.0,
            "amplitude_high": 8.0,
        }
    )
    CANDIDATE_FUNNEL_SOURCES: dict[str, bool] = field(
        default_factory=lambda: {
            "gene": True,
            "board_ladder": True,
            "activity": True,
            "fund_flow": True,
            "auction": True,
            "catalyst": True,
            "watchlist_in": True,
        }
    )
    CANDIDATE_FUNNEL_CACHE_TTL: int = 60

    # === ML过滤（未来实验方向，当前默认关闭） ===
    # 以下字段为未来 ML 实验预留，当前未使用
    AI_CONFIDENCE_THRESHOLD: float = 0.60
    AI_RETRAIN_DAYS: int = 1
    AI_OOS_THRESHOLD: float = 0.6
    AI_AUTO_ROLLBACK_DAYS: int = 5

    # === 回测 ===
    BACKTEST_INITIAL_CAPITAL: float = 1_000_000.0
    BACKTEST_LOOKBACK_DAYS: int = 252

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
        cfg.GENE_QUALIFY_THRESHOLD = _parse_float(
            "VR_GENE_QUALIFY_THRESHOLD", os.getenv("VR_GENE_QUALIFY_THRESHOLD"),
            cfg.GENE_QUALIFY_THRESHOLD,
        )
    if os.getenv("VR_GENE_HIGH_THRESHOLD"):
        cfg.GENE_HIGH_THRESHOLD = _parse_float(
            "VR_GENE_HIGH_THRESHOLD", os.getenv("VR_GENE_HIGH_THRESHOLD"),
            cfg.GENE_HIGH_THRESHOLD,
        )

    # 推荐阈值
    if os.getenv("VR_RECOMMEND_HIGH_THRESHOLD"):
        cfg.RECOMMEND_HIGH_THRESHOLD = _parse_float(
            "VR_RECOMMEND_HIGH_THRESHOLD", os.getenv("VR_RECOMMEND_HIGH_THRESHOLD"),
            cfg.RECOMMEND_HIGH_THRESHOLD,
        )
    if os.getenv("VR_RECOMMEND_MEDIUM_THRESHOLD"):
        cfg.RECOMMEND_MEDIUM_THRESHOLD = _parse_float(
            "VR_RECOMMEND_MEDIUM_THRESHOLD", os.getenv("VR_RECOMMEND_MEDIUM_THRESHOLD"),
            cfg.RECOMMEND_MEDIUM_THRESHOLD,
        )

    # 推送
    if os.getenv("VR_FEISHU_WEBHOOK"):
        cfg.PUSH_CHANNELS = ["feishu"]

    # 通知渠道环境变量（S015 R1：逻辑拆到 config.notification.apply_notification_env）
    apply_notification_env(cfg, _parse_bool, _parse_int, os.getenv)

    # 性能
    if os.getenv("VR_CONCURRENT_REQUESTS"):
        cfg.CONCURRENT_REQUESTS = _parse_int(
            "VR_CONCURRENT_REQUESTS", os.getenv("VR_CONCURRENT_REQUESTS"),
            cfg.CONCURRENT_REQUESTS,
        )
    if os.getenv("VR_BATCH_SIZE"):
        cfg.BATCH_SIZE = _parse_int(
            "VR_BATCH_SIZE", os.getenv("VR_BATCH_SIZE"), cfg.BATCH_SIZE,
        )

    return cfg


# 全局配置单例
default_config = load_config()
