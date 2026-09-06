# -*- coding: utf-8 -*-
"""通知渠道配置 —— 拆自 ``config.py``（S015 R1）。

集中管理推送/通知相关 30+ 配置项：飞书 / 钉钉 / 邮件 / 微信 / Telegram /
Pushover / PushPlus / Server酱3 / 自定义 Webhook / Discord / Slack / AstrBot /
ntfy / Gotify，以及推送节流（``PUSH_THROTTLE``）与静默时段（``PUSH_QUIET_HOURS``）。

默认值与原 ``config.py`` 完全一致；经 ``config/__init__.py`` 经 dataclass 继承
合并进 ``AssistantDefaultConfig`` 并 re-export，保持向后兼容
（``from config import default_config`` / ``AssistantDefaultConfig`` 不变）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class NotificationConfig:
    """通知 / 推送渠道默认配置（30+ 项）。"""

    # === 推送 ===
    PUSH_CHANNELS: list[str] = field(default_factory=lambda: ["feishu"])
    PUSH_THROTTLE: dict[str, Any] = field(
        default_factory=lambda: {
            "same_ticker_interval_sec": 300,
            "max_daily_per_ticker": 3,
            "max_daily_total": 20,
        }
    )

    # === 推送（静默时段） ===
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
    wechat_token: str = ""  # 企业微信回调 token（签名校验，被动接收消息用）
    wechat_encoding_aes_key: str = ""  # 消息加解密 key（可选，不配则明文模式）
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


# 通知渠道环境变量映射（env_name → cfg 字段名）。原 config.py 的 _FEISHU_ENV_MAP。
NOTIFICATION_ENV_MAP: dict[str, str] = {
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
    "WECHAT_TOKEN": "wechat_token",
    "WECHAT_ENCODING_AES_KEY": "wechat_encoding_aes_key",
}


def apply_notification_env(
    cfg,
    parse_bool: Callable[..., bool],
    parse_int: Callable[..., int],
    getenv: Callable[[str], str | None],
) -> None:
    """将通知渠道环境变量覆盖到 ``cfg`` 上。

    类型派发与原 ``config.load_config`` 一致：bool 字段走 ``parse_bool``、
    int 字段走 ``parse_int``、list 字段按逗号切分、其余按字符串原样赋值。
    非法值由 ``parse_*`` 告警并沿用默认（S015 R2）。
    """
    for env_key, cfg_key in NOTIFICATION_ENV_MAP.items():
        val = getenv(env_key)
        if val is None:
            continue
        if not hasattr(cfg, cfg_key):
            continue
        current = getattr(cfg, cfg_key)
        # 注意：bool 是 int 子类，必须先判 bool 再判 int
        if isinstance(current, bool):
            setattr(cfg, cfg_key, parse_bool(env_key, val, current))
        elif isinstance(current, int):
            setattr(cfg, cfg_key, parse_int(env_key, val, current))
        elif isinstance(current, list):
            setattr(cfg, cfg_key, [v.strip() for v in val.split(",") if v.strip()])
        else:
            setattr(cfg, cfg_key, val)
