# -*- coding: utf-8 -*-
"""通知服务核心 — 组合所有 Mixin 与 Sender 类"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from config import default_config

from notification.notification_noise import (
    NotificationNoiseDecision,
    evaluate_notification_noise,
    record_notification_noise,
    release_notification_noise,
)
from notification.notification_routing import (
    get_notification_route_config,
    split_notification_route_channels,
)
from notification.notification_channel import NotificationChannel, ChannelDetector
from notification.notification_result import ChannelAttemptResult, NotificationDispatchResult

from .notification_formatters import NotificationFormatterMixin
from .notification_report_generator import NotificationReportMixin
from .notification_dispatcher import NotificationDispatcherMixin

from notification.senders.feishu_sender import FeishuSender
from notification.senders.wechat_sender import WechatSender
from notification.senders.telegram_sender import TelegramSender
from notification.senders.email_sender import EmailSender
from notification.senders.custom_webhook_sender import CustomWebhookSender
from notification.senders.dingtalk_sender import DingtalkSender
from notification.senders.discord_sender import DiscordSender
from notification.senders.gotify_sender import GotifySender
from notification.senders.ntfy_sender import NtfySender
from notification.senders.pushover_sender import PushoverSender
from notification.senders.pushplus_sender import PushplusSender
from notification.senders.serverchan3_sender import Serverchan3Sender
from notification.senders.slack_sender import SlackSender
from notification.senders.astrbot_sender import AstrbotSender

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    """Best-effort float conversion; handles `"3.2%"` and `"1,234"` shapes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


if TYPE_CHECKING:
    pass  # AnalysisResult not needed for core notification service


class NotificationService(
    NotificationDispatcherMixin,
    NotificationReportMixin,
    NotificationFormatterMixin,
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    FeishuSender,
    GotifySender,
    NtfySender,
    PushoverSender,
    PushplusSender,
    Serverchan3Sender,
    SlackSender,
    TelegramSender,
    WechatSender,
    DingtalkSender,
):
    """
    通知服务
    
    职责：
    1. 生成 Markdown 格式的分析日报
    2. 向所有已配置的渠道推送消息（多渠道并发）
    3. 支持本地保存日报
    
    支持的渠道：
    - 企业微信 Webhook
    - 飞书 Webhook
    - Telegram Bot
    - 邮件 SMTP
    - Pushover（手机/桌面推送）
    
    注意：所有已配置的渠道都会收到推送
    """

    def __init__(self, source_message: Optional[Any] = None):
        """
        初始化通知服务
        
        检测所有已配置的渠道，推送时会向所有渠道发送
        """
        self._config = default_config
        self._source_message = source_message
        self._context_channels: List[str] = []

        # Markdown 转图片（Issue #289）
        self._markdown_to_image_channels = set(
            getattr(default_config, 'markdown_to_image_channels', []) or []
        )
        self._markdown_to_image_max_chars = getattr(
            default_config, 'markdown_to_image_max_chars', 15000
        )

        # 仅分析结果摘要（Issue #262）：true 时只推送汇总，不含个股详情
        self._report_summary_only = getattr(default_config, 'report_summary_only', False)
        self._report_show_llm_model = getattr(default_config, 'report_show_llm_model', True)
        self._history_compare_cache: Dict[Tuple[int, Tuple[Tuple[str, str], ...]], Dict[str, List[Dict[str, Any]]]] = {}

        # 初始化各渠道
        AstrbotSender.__init__(self, default_config)
        CustomWebhookSender.__init__(self, default_config)
        DiscordSender.__init__(self, default_config)
        EmailSender.__init__(self, default_config)
        FeishuSender.__init__(self, default_config)
        GotifySender.__init__(self, default_config)
        NtfySender.__init__(self, default_config)
        PushoverSender.__init__(self, default_config)
        PushplusSender.__init__(self, default_config)
        Serverchan3Sender.__init__(self, default_config)
        SlackSender.__init__(self, default_config)
        TelegramSender.__init__(self, default_config)
        WechatSender.__init__(self, default_config)
        DingtalkSender.__init__(self, default_config)

        # 检测所有已配置的渠道
        self._available_channels = self._detect_all_channels()
        if self._extract_dingtalk_session_webhook() is not None:
            self._context_channels.append("钉钉会话")
        if self._extract_feishu_reply_info() is not None:
            self._context_channels.append("飞书会话")

        if not self._available_channels and not self._context_channels:
            logger.warning("未配置有效的通知渠道，将不发送推送通知")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            channel_names.extend(self._context_channels)
            logger.info(f"已配置 {len(channel_names)} 个通知渠道：{', '.join(channel_names)}")


_notification_service_instance: "NotificationService | None" = None


def get_notification_service() -> NotificationService:
    """获取通知服务实例（M15：单例，避免高频场景重复初始化 14 个 Sender）"""
    global _notification_service_instance
    if _notification_service_instance is None:
        _notification_service_instance = NotificationService()
    return _notification_service_instance


def send_daily_report(results: List[Any]) -> bool:
    """
    发送每日报告的快捷方式
    
    自动识别渠道并推送
    """
    service = get_notification_service()
    
    # 生成报告
    report = service.generate_daily_report(results)
    
    # 保存到本地
    service.save_report_to_file(report)
    
    # 推送到配置的渠道（自动识别）
    return service.send(report)
