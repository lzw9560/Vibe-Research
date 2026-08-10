# -*- coding: utf-8 -*-
"""配置管理 —— 默认配置 + 用户配置覆盖。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

# 自动加载 .env 文件（项目根目录下的 backend/.env）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


@dataclass
class AssistantDefaultConfig:
    """投研助手默认配置。"""

    # === 基因选股 ===
    GENE_LOOKBACK_DAYS: int = 252
    # 60→50（2026-08-10 grill）：强封板市况下炸板后溢价恒 0（占权重 15%），total_score 结构性
    # 上限 ~52，阈值 60 会清空候选池、L2 战法层无输入；降到 50 让头部候选进战法层。
    # 权重口径调整（炸板后溢价降权/改口径）待 S041 回测验证后正式改稿。
    GENE_QUALIFY_THRESHOLD: float = 50.0
    # 75→60（2026-08-10 grill）：与 config/__init__.py 同步；本文件被 config/ 包 shadow，
    # 但保留不一致会造成两处口径坑。
    GENE_HIGH_THRESHOLD: float = 60.0
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

    # === ML过滤（未来实验方向，当前默认关闭） ===
    # 以下字段为未来 ML 实验预留，当前未使用
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
    BACKTEST_LOOKBACK_DAYS: int = 252

    # === 性能 ===
    CONCURRENT_REQUESTS: int = 10
    BATCH_SIZE: int = 100
    CACHE_TTL_HOURS: int = 12

    # === 数据库 ===
    # deprecated: 用 config.GENE_SCORES_DB_PATH 替代（S037）；本文件已被 config/ 包遮蔽
    DB_PATH: str = "gene_scores.db"

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

    # === 通知渠道 ===
    feishu_webhook_url: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_chat_id: str = ""
    feishu_stream_enabled: bool = False
    feishu_receive_id_type: str = "chat_id"
    feishu_domain: str = "feishu"
    feishu_max_bytes: int = 20000
    feishu_send_as_file: bool = False
    feishu_webhook_secret: str = ""
    feishu_webhook_keyword: str = ""
    feishu_webhook_verify_ssl: bool = True
    feishu_prefer_app_bot: bool = False
    dingtalk_webhook_url: str = ""
    dingtalk_secret: str = ""
    dingtalk_stream_enabled: bool = False
    dingtalk_app_key: str = ""
    dingtalk_app_secret: str = ""
    merge_email_notification: bool = False
    seal_plate_notification_enabled: bool = False
    single_stock_notify: bool = False
    report_type: str = "brief"
    report_language: str = "zh"
    report_summary_only: bool = False
    report_integrity_enabled: bool = False
    wechat_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    email_sender: str = ""
    email_password: str = ""
    email_receivers: list[str] = field(default_factory=list)
    pushover_user_key: str = ""
    pushover_api_token: str = ""
    pushplus_token: str = ""
    serverchan3_sendkey: str = ""
    custom_webhook_urls: list[str] = field(default_factory=list)
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""
    astrbot_url: str = ""
    ntfy_url: str = ""
    gotify_url: str = ""


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

    # 通知渠道环境变量映射
    _FEISHU_ENV_MAP = {
        "FEISHU_WEBHOOK_URL": "feishu_webhook_url",
        "FEISHU_APP_ID": "feishu_app_id",
        "FEISHU_APP_SECRET": "feishu_app_secret",
        "FEISHU_CHAT_ID": "feishu_chat_id",
        "FEISHU_STREAM_ENABLED": "feishu_stream_enabled",
        "FEISHU_RECEIVE_ID_TYPE": "feishu_receive_id_type",
        "FEISHU_DOMAIN": "feishu_domain",
        "FEISHU_MAX_BYTES": "feishu_max_bytes",
        "FEISHU_SEND_AS_FILE": "feishu_send_as_file",
        "FEISHU_WEBHOOK_SECRET": "feishu_webhook_secret",
        "FEISHU_WEBHOOK_KEYWORD": "feishu_webhook_keyword",
        "FEISHU_WEBHOOK_VERIFY_SSL": "feishu_webhook_verify_ssl",
        "FEISHU_PREFER_APP_BOT": "feishu_prefer_app_bot",
        "DINGTALK_WEBHOOK_URL": "dingtalk_webhook_url",
        "DINGTALK_SECRET": "dingtalk_secret",
        "DINGTALK_STREAM_ENABLED": "dingtalk_stream_enabled",
        "DINGTALK_APP_KEY": "dingtalk_app_key",
        "DINGTALK_APP_SECRET": "dingtalk_app_secret",
        "MERGE_EMAIL_NOTIFICATION": "merge_email_notification",
        "SEAL_PLATE_NOTIFICATION_ENABLED": "seal_plate_notification_enabled",
        "SINGLE_STOCK_NOTIFY": "single_stock_notify",
        "REPORT_TYPE": "report_type",
        "REPORT_LANGUAGE": "report_language",
        "REPORT_SUMMARY_ONLY": "report_summary_only",
        "REPORT_INTEGRITY_ENABLED": "report_integrity_enabled",
    }
    for env_key, cfg_key in _FEISHU_ENV_MAP.items():
        val = os.getenv(env_key)
        if val is not None:
            if hasattr(cfg, cfg_key):
                current = getattr(cfg, cfg_key)
                if isinstance(current, bool):
                    setattr(cfg, cfg_key, val.lower() in ("true", "1", "yes"))
                elif isinstance(current, int):
                    setattr(cfg, cfg_key, int(val))
                elif isinstance(current, list):
                    setattr(cfg, cfg_key, [v.strip() for v in val.split(",") if v.strip()])
                else:
                    setattr(cfg, cfg_key, val)

    # 性能
    if os.getenv("VR_CONCURRENT_REQUESTS"):
        cfg.CONCURRENT_REQUESTS = int(os.getenv("VR_CONCURRENT_REQUESTS"))
    if os.getenv("VR_BATCH_SIZE"):
        cfg.BATCH_SIZE = int(os.getenv("VR_BATCH_SIZE"))

    return cfg


# 全局配置单例
default_config = load_config()
