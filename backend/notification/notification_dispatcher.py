# -*- coding: utf-8 -*-
"""通知分发 Mixin"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

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

if TYPE_CHECKING:
    pass  # AnalysisResult not needed for dispatcher

logger = logging.getLogger(__name__)


def _sanitize_notification_diagnostics(text: str) -> str:
    """Sanitize diagnostic text for safe logging."""
    return text.replace("\n", " ").replace("\r", " ")[:500]


class NotificationDispatcherMixin:
    """通知分发方法集合。"""

    # --- 渠道配置检测表 ---
    # 每个条目: (channel, required_attrs, optional_resolver)
    # optional_resolver 是可选的 callable，接收 config 返回是否可用
    _CHANNEL_CONFIG_CHECKS: List[Tuple[NotificationChannel, List[str]]] = [
        (NotificationChannel.WECHAT, ["wechat_webhook_url"]),
        (NotificationChannel.TELEGRAM, ["telegram_bot_token", "telegram_chat_id"]),
        (NotificationChannel.EMAIL, ["email_sender", "email_password"]),
        (NotificationChannel.PUSHOVER, ["pushover_user_key", "pushover_api_token"]),
        (NotificationChannel.PUSHPLUS, ["pushplus_token"]),
        (NotificationChannel.SERVERCHAN3, ["serverchan3_sendkey"]),
        (NotificationChannel.CUSTOM, ["custom_webhook_urls"]),
        (NotificationChannel.DISCORD, ["discord_webhook_url"]),
        (NotificationChannel.SLACK, ["slack_webhook_url"]),
        (NotificationChannel.ASTRBOT, ["astrbot_url"]),
    ]

    @staticmethod
    def _resolve_feishu(config: Any) -> bool:
        return bool(
            getattr(config, "feishu_webhook_url", None)
            or (
                getattr(config, "feishu_app_id", None)
                and getattr(config, "feishu_app_secret", None)
                and getattr(config, "feishu_chat_id", None)
            )
        )

    @staticmethod
    def _resolve_ntfy(config: Any) -> bool:
        from notification.senders.ntfy_sender import resolve_ntfy_endpoint
        server_url, topic = resolve_ntfy_endpoint(getattr(config, "ntfy_url", None))
        return bool(server_url and topic)

    @staticmethod
    def _resolve_gotify(config: Any) -> bool:
        from notification.senders.gotify_sender import resolve_gotify_message_endpoint
        endpoint = resolve_gotify_message_endpoint(getattr(config, "gotify_url", None))
        return bool(endpoint and (getattr(config, "gotify_token", None) or "").strip())

    @staticmethod
    def _resolve_discord_bot(config: Any) -> bool:
        return bool(
            getattr(config, "discord_bot_token", None)
            and getattr(config, "discord_main_channel_id", None)
        )

    @staticmethod
    def _resolve_slack_bot(config: Any) -> bool:
        return bool(
            getattr(config, "slack_bot_token", None)
            and getattr(config, "slack_channel_id", None)
        )

    @staticmethod
    def detect_configured_channels(config: Any) -> List[NotificationChannel]:
        """表驱动：检测所有静态配置的通知渠道。"""
        channels: List[NotificationChannel] = []

        for channel, required_attrs in NotificationDispatcherMixin._CHANNEL_CONFIG_CHECKS:
            if all(getattr(config, attr, None) for attr in required_attrs):
                channels.append(channel)

        # 特殊渠道 Feishu（支持 Webhook 和 App Bot 两种模式）
        if NotificationDispatcherMixin._resolve_feishu(config) and NotificationChannel.FEISHU not in channels:
            channels.append(NotificationChannel.FEISHU)

        # 特殊渠道 NTFY（需要自定义解析）
        if NotificationDispatcherMixin._resolve_ntfy(config):
            channels.append(NotificationChannel.NTFY)

        # Gotify（需要自定义解析）
        if NotificationDispatcherMixin._resolve_gotify(config):
            channels.append(NotificationChannel.GOTIFY)

        # Discord bot 模式（webhook 已在上表覆盖）
        if NotificationDispatcherMixin._resolve_discord_bot(config) and NotificationChannel.DISCORD not in channels:
            channels.append(NotificationChannel.DISCORD)

        # Slack bot 模式（webhook 已在上表覆盖）
        if NotificationDispatcherMixin._resolve_slack_bot(config) and NotificationChannel.SLACK not in channels:
            channels.append(NotificationChannel.SLACK)

        return channels

    def _detect_all_channels(self) -> List[NotificationChannel]:
        """
        检测所有已配置的渠道

        Returns:
            已配置的渠道列表
        """
        return self.detect_configured_channels(self._config)

    def is_available(self) -> bool:
        """检查通知服务是否可用（至少有一个渠道或上下文渠道）"""
        return len(self._available_channels) > 0 or self._has_context_channel()

    def get_available_channels(self) -> List[NotificationChannel]:
        """获取所有已配置的渠道"""
        return self._available_channels

    def get_channels_for_route(
        self,
        route_type: Optional[str],
        channels: Optional[List[NotificationChannel]] = None,
    ) -> List[NotificationChannel]:
        """Return channels allowed for a route type.

        ``route_type=None`` keeps the legacy behavior and returns all supplied
        static channels. Empty route config also keeps all supplied channels.
        Non-empty route config that matches no enabled channel returns an empty
        list.
        """
        target_channels = list(channels if channels is not None else self._available_channels)
        if route_type is None:
            return target_channels

        route_config = get_notification_route_config(route_type)
        if route_config is None:
            logger.warning("未知通知路由类型 %s，沿用全部已配置渠道", route_type)
            return target_channels

        configured_route_channels = getattr(self._config, route_config["config_attr"], []) or []
        if not configured_route_channels:
            return target_channels

        valid_channels, invalid_channels = split_notification_route_channels(configured_route_channels)
        if invalid_channels:
            logger.warning(
                "%s 包含未知通知渠道，将忽略: %s",
                route_config["env_key"],
                ", ".join(invalid_channels),
            )

        allowed = set(valid_channels)
        return [channel for channel in target_channels if channel.value in allowed]

    def get_channel_names(self) -> str:
        """获取所有已配置渠道的名称"""
        names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
        if self._has_context_channel():
            names.append("钉钉会话")
        return ', '.join(names)

    def evaluate_noise_control(
        self,
        content: str,
        *,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
    ) -> NotificationNoiseDecision:
        """Evaluate static-channel notification noise controls."""
        return evaluate_notification_noise(
            self._config,
            content=content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
        )

    @staticmethod
    def record_noise_control(decision: NotificationNoiseDecision) -> None:
        """Record static-channel notification noise state after a successful send."""
        record_notification_noise(decision)

    @staticmethod
    def release_noise_control(decision: NotificationNoiseDecision) -> None:
        """Release static-channel in-flight noise reservation after send failure."""
        release_notification_noise(decision)

    # ===== Context channel =====

    def _has_context_channel(self) -> bool:
        """判断是否存在基于消息上下文的临时渠道（如钉钉会话、飞书会话）"""
        return (
            self._extract_dingtalk_session_webhook() is not None
            or self._extract_feishu_reply_info() is not None
            or self._extract_telegram_context_chat_id() is not None
        )

    def _source_platform(self) -> str:
        """Return normalized platform from the source bot message."""
        platform = getattr(self._source_message, "platform", "")
        if hasattr(platform, "value"):
            platform = platform.value
        return str(platform or "").lower()

    def _extract_telegram_context_chat_id(self) -> Optional[str]:
        """从来源消息中提取 Telegram 上下文 chat_id（用于异步回复）。"""
        if self._source_message is None:
            return None
        if not hasattr(self._source_message, "platform"):
            return None
        if self._source_platform() != "telegram":
            return None
        raw_data = getattr(self._source_message, "raw_data", {}) or {}
        for candidate in (
            getattr(self._source_message, "chat_id", ""),
            raw_data.get("chat_id"),
            raw_data.get("message", {}).get("chat", {}).get("id") if isinstance(raw_data.get("message"), dict) else None,
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if candidate is not None and not isinstance(candidate, str):
                candidate_text = str(candidate).strip()
                if candidate_text:
                    return candidate_text
        return None

    def should_broadcast_static_channels(self) -> bool:
        """Whether static notification channels should receive this dispatch."""
        return not self._has_context_channel()

    def _extract_dingtalk_session_webhook(self) -> Optional[str]:
        """从来源消息中提取钉钉会话 Webhook（用于 Stream 模式回复）"""
        if self._source_message is None:
            return None
        raw_data = getattr(self._source_message, "raw_data", {}) or {}
        if not isinstance(raw_data, dict):
            return None
        session_webhook = (
            raw_data.get("_session_webhook")
            or raw_data.get("sessionWebhook")
            or raw_data.get("session_webhook")
            or raw_data.get("session_webhook_url")
        )
        if not session_webhook and isinstance(raw_data.get("headers"), dict):
            session_webhook = raw_data["headers"].get("sessionWebhook")
        return session_webhook

    def _extract_feishu_reply_info(self) -> Optional[Dict[str, str]]:
        """
        从来源消息中提取飞书回复信息（用于 Stream 模式回复）
        
        Returns:
            包含 chat_id 的字典，或 None
        """
        if self._source_message is None:
            return None
        if not hasattr(self._source_message, "platform"):
            return None
        if getattr(self._source_message, "platform", "") != "feishu":
            return None
        chat_id = getattr(self._source_message, "chat_id", "")
        if not chat_id:
            return None
        return {"chat_id": chat_id}

    def send_to_context(self, content: str) -> bool:
        """
        向基于消息上下文的渠道发送消息（例如钉钉 Stream 会话）
        
        Args:
            content: Markdown 格式内容
        """
        return self._send_via_source_context(content)
    
    def _send_via_source_context(self, content: str) -> bool:
        """
        使用消息上下文（如钉钉/飞书会话）发送一份报告
        
        主要用于从机器人 Stream 模式触发的任务，确保结果能回到触发的会话。
        """
        success = False
        
        # 尝试钉钉会话
        session_webhook = self._extract_dingtalk_session_webhook()
        if session_webhook:
            try:
                if self._send_dingtalk_chunked(session_webhook, content, max_bytes=20000):
                    logger.info("已通过钉钉会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("钉钉会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"钉钉会话（Stream）推送异常: {e}")

        # 尝试飞书会话
        feishu_info = self._extract_feishu_reply_info()
        if feishu_info:
            try:
                if self._send_feishu_stream_reply(feishu_info["chat_id"], content):
                    logger.info("已通过飞书会话（Stream）推送报告")
                    success = True
                else:
                    logger.error("飞书会话（Stream）推送失败")
            except Exception as e:
                logger.error(f"飞书会话（Stream）推送异常: {e}")

        # 尝试 Telegram 会话上下文（按来源 chat_id 回执）
        telegram_chat_id = self._extract_telegram_context_chat_id()
        if telegram_chat_id:
            try:
                if self.send_to_telegram(content, chat_id=telegram_chat_id):
                    logger.info("已通过 Telegram 上下文会话推送报告")
                    success = True
                else:
                    logger.error("Telegram 上下文会话推送失败")
            except Exception as e:
                logger.error(f"Telegram 上下文会话推送异常: {e}")

        return success

    def _send_feishu_stream_reply(self, chat_id: str, content: str) -> bool:
        """
        通过飞书 Stream 模式发送消息到指定会话
        
        Args:
            chat_id: 飞书会话 ID
            content: 消息内容
            
        Returns:
            是否发送成功
        """
        try:
            from notification.senders.feishu_sender import _ensure_feishu_sdk_loaded
            if not _ensure_feishu_sdk_loaded():
                logger.warning("飞书 SDK 不可用，无法发送 Stream 回复")
                return False
            
            from config import default_config
            config = default_config
            
            app_id = getattr(config, 'feishu_app_id', None)
            app_secret = getattr(config, 'feishu_app_secret', None)
            
            if not app_id or not app_secret:
                logger.warning("飞书 APP_ID 或 APP_SECRET 未配置")
                return False
            
            # 创建回复客户端
            from notification.senders.feishu_sender import _get_lark_client_builder, _get_create_message_request
            lark_client_builder = _get_lark_client_builder()
            create_message_request = _get_create_message_request()
            
            from lark_oapi.api.im.v1 import CreateMessageRequest
            client = lark_client_builder(app_id, app_secret).build()
            
            # 飞书文本消息有长度限制，需要分批发送
            max_bytes = getattr(config, 'feishu_max_bytes', 20000)
            content_bytes = len(content.encode('utf-8'))
            
            if content_bytes > max_bytes:
                return self._send_feishu_stream_chunked(client, chat_id, content, max_bytes)
            
            request = CreateMessageRequest(
                receive_id=chat_id,
                request_body={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": content}),
                }
            )
            response = client.im.v1.message.create(request)
            return response.success()
            
        except ImportError as e:
            logger.error(f"导入飞书 Stream 模块失败: {e}")
            return False
        except Exception as e:
            logger.error(f"飞书 Stream 回复异常: {e}")
            return False

    def _send_feishu_stream_chunked(
        self, 
        client: Any, 
        chat_id: str, 
        content: str, 
        max_bytes: int
    ) -> bool:
        """
        分批发送长消息到飞书（Stream 模式）
        
        Args:
            client: Lark client 实例
            chat_id: 飞书会话 ID
            content: 完整消息内容
            max_bytes: 单条消息最大字节数
            
        Returns:
            是否全部发送成功
        """
        import time
        import json
        from lark_oapi.api.im.v1 import CreateMessageRequest
        
        def get_bytes(s: str) -> int:
            return len(s.encode('utf-8'))
        
        # 按段落或分隔线分割
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 按行分割
            sections = content.split("\n")
            separator = "\n"
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            if current_bytes + section_bytes > max_bytes:
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 发送每个分块
        success = True
        for i, chunk in enumerate(chunks):
            if i > 0:
                time.sleep(0.5)  # 避免请求过快
            
            request = CreateMessageRequest(
                receive_id=chat_id,
                request_body={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": chunk}),
                }
            )
            response = client.im.v1.message.create(request)
            if not response.success():
                success = False
                logger.error(f"飞书 Stream 分块 {i+1}/{len(chunks)} 发送失败")
        
        return success

    def _should_use_image_for_channel(
        self, channel: NotificationChannel, image_bytes: Optional[bytes]
    ) -> bool:
        """
        Decide whether to send as image for the given channel (Issue #289).

        Fallback rules (send as Markdown text instead of image):
        - image_bytes is None: conversion failed / imgkit not installed / content over max_chars
        - WeChat: image exceeds ~2MB limit
        """
        if channel.value not in self._markdown_to_image_channels or image_bytes is None:
            return False
        if channel == NotificationChannel.WECHAT:
            from notification.senders.feishu_sender import WECHAT_IMAGE_MAX_BYTES
            if len(image_bytes) > WECHAT_IMAGE_MAX_BYTES:
                logger.warning(
                    "企业微信图片超限 (%d bytes)，回退为 Markdown 文本发送",
                    len(image_bytes),
                )
                return False
        return True

    def send_with_results(
        self,
        content: str,
        email_stock_codes: Optional[List[str]] = None,
        email_send_to_all: bool = False,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
    ) -> NotificationDispatchResult:
        """
        Send a notification and return per-channel diagnostics.

        ``send()`` keeps the historical bool API and delegates here.

        Fallback rules (Markdown-to-image, Issue #289):
        - When image_bytes is None (conversion failed / imgkit not installed /
          content over max_chars): all channels configured for image will send
          as Markdown text instead.
        - When WeChat image exceeds ~2MB: that channel falls back to Markdown text.

        Args:
            content: 消息内容（Markdown 格式）
            email_stock_codes: 股票代码列表（可选，用于邮件渠道路由到对应分组邮箱，Issue #268）
            email_send_to_all: 邮件是否发往所有配置邮箱（用于大盘复盘等无股票归属的内容）
            route_type: 通知路由类型；None 保持旧行为，report/alert/system_error 按配置过滤静态渠道
            severity: 通知严重级别；未设置时按路由类型推断
            dedup_key: 可选稳定去重 key；未设置时使用内容 hash
            cooldown_key: 可选冷却 key；未设置时使用路由/级别默认 key

        Returns:
            Structured dispatch diagnostics.
        """
        context_success = self.send_to_context(content)
        if not self.should_broadcast_static_channels():
            if context_success:
                logger.info("已通过上下文会话完成推送，跳过静态通知渠道")
                return NotificationDispatchResult(
                    dispatched=True,
                    success=True,
                    status="sent",
                    channel_results=[ChannelAttemptResult(channel="__context__", success=True)],
                )
            logger.warning("交互式上下文推送失败，已跳过静态通知渠道")
            return NotificationDispatchResult(
                dispatched=True,
                success=False,
                status="all_failed",
                channel_results=[
                    ChannelAttemptResult(
                        channel="__context__",
                        success=False,
                        error_code="send_failed",
                        retryable=True,
                    )
                ],
                message="interactive context delivery failed; static channels skipped",
            )

        if not self._available_channels:
            if context_success:
                logger.info("已通过消息上下文渠道完成推送（无其他通知渠道）")
                return NotificationDispatchResult(
                    dispatched=True,
                    success=True,
                    status="sent",
                    channel_results=[ChannelAttemptResult(channel="__context__", success=True)],
                )
            logger.warning("通知服务不可用，跳过推送")
            return NotificationDispatchResult(
                dispatched=False,
                success=False,
                status="no_channel",
                message="notification service unavailable",
            )

        target_channels = self.get_channels_for_route(route_type)
        if not target_channels:
            if context_success:
                logger.info("已通过消息上下文渠道完成推送（路由后无其他通知渠道）")
                return NotificationDispatchResult(
                    dispatched=True,
                    success=True,
                    status="sent",
                    channel_results=[ChannelAttemptResult(channel="__context__", success=True)],
                )
            logger.warning("通知路由 %s 未命中任何已配置渠道，跳过静态通知渠道", route_type)
            return NotificationDispatchResult(
                dispatched=False,
                success=False,
                status="no_channel",
                message=f"notification route {route_type} has no configured channel",
            )

        noise_decision = self.evaluate_noise_control(
            content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
        )
        if not noise_decision.should_send:
            logger.info(noise_decision.message)
            status = "sent" if context_success else "noise_suppressed"
            results = [ChannelAttemptResult(channel="__context__", success=True)] if context_success else []
            return NotificationDispatchResult(
                dispatched=bool(context_success),
                success=bool(context_success),
                status=status,
                channel_results=results,
                message=noise_decision.message,
            )

        # Markdown to image (Issue #289): convert once if any channel needs it.
        # Per-channel decision via _should_use_image_for_channel (see send() docstring for fallback rules).
        image_bytes = None
        channels_needing_image = {
            ch for ch in target_channels
            if ch.value in self._markdown_to_image_channels
            and ch not in {NotificationChannel.NTFY, NotificationChannel.GOTIFY}
        }
        if channels_needing_image:
            try:
                from notification.senders.feishu_sender import markdown_to_image
                image_bytes = markdown_to_image(
                    content, max_chars=self._markdown_to_image_max_chars
                )
                if image_bytes:
                    logger.info("Markdown 已转换为图片，将向 %s 发送图片",
                                [ch.value for ch in channels_needing_image])
                elif channels_needing_image:
                    try:
                        engine = getattr(default_config, "md2img_engine", "wkhtmltoimage")
                    except Exception:
                        engine = "wkhtmltoimage"
                    hint = (
                        "npm i -g markdown-to-file" if engine == "markdown-to-file"
                        else "wkhtmltopdf (apt install wkhtmltopdf / brew install wkhtmltopdf)"
                    )
                    logger.warning(
                        "Markdown 转图片失败，将回退为文本发送。请检查 MARKDOWN_TO_IMAGE_CHANNELS 配置并安装 %s",
                        hint,
                    )
            except Exception as e:
                logger.warning("Markdown 转图片失败: %s", e)

        channel_names = ', '.join(ChannelDetector.get_channel_name(ch) for ch in target_channels)
        logger.info(f"正在向 {len(target_channels)} 个渠道发送通知：{channel_names}")

        success_count = 0
        fail_count = 0
        channel_results: List[ChannelAttemptResult] = []

        for channel in target_channels:
            channel_name = ChannelDetector.get_channel_name(channel)
            started_at = time.monotonic()
            try:
                result = self._send_to_static_channel(
                    channel,
                    content,
                    image_bytes=image_bytes,
                    email_stock_codes=email_stock_codes,
                    email_send_to_all=email_send_to_all,
                )
                latency_ms = int((time.monotonic() - started_at) * 1000)

                if result:
                    success_count += 1
                else:
                    fail_count += 1
                channel_results.append(
                    ChannelAttemptResult(
                        channel=channel.value,
                        success=bool(result),
                        error_code=None if result else "send_failed",
                        retryable=not bool(result),
                        latency_ms=latency_ms,
                    )
                )

            except Exception as e:
                logger.error(f"{channel_name} 发送失败: {e}")
                fail_count += 1
                channel_results.append(
                    ChannelAttemptResult(
                        channel=channel.value,
                        success=False,
                        error_code="exception",
                        retryable=True,
                        latency_ms=int((time.monotonic() - started_at) * 1000),
                        diagnostics=_sanitize_notification_diagnostics(str(e)),
                    )
                )

        logger.info(f"通知发送完成：成功 {success_count} 个，失败 {fail_count} 个")
        if success_count > 0:
            self.record_noise_control(noise_decision)
        else:
            self.release_noise_control(noise_decision)
        success = success_count > 0 or context_success
        if success_count > 0 and fail_count > 0:
            status = "partial_failed"
        elif success_count > 0 or context_success:
            status = "sent"
        else:
            status = "all_failed"
        if context_success:
            channel_results.insert(0, ChannelAttemptResult(channel="__context__", success=True))
        return NotificationDispatchResult(
            dispatched=True,
            success=success,
            status=status,
            channel_results=channel_results,
        )

    def send(
        self,
        content: str,
        email_stock_codes: Optional[List[str]] = None,
        email_send_to_all: bool = False,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
    ) -> bool:
        """
        统一发送接口 - 向所有已配置的渠道发送。

        Returns:
            是否至少有一个渠道发送成功
        """
        result = self.send_with_results(
            content,
            email_stock_codes=email_stock_codes,
            email_send_to_all=email_send_to_all,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
        )
        return bool(result.success)

    def save_report_to_file(
        self, 
        content: str, 
        filename: Optional[str] = None
    ) -> str:
        """
        保存日报到本地文件
        
        Args:
            content: 日报内容
            filename: 文件名（可选，默认按日期生成）
            
        Returns:
            保存的文件路径
        """
        from pathlib import Path
        
        if filename is None:
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"report_{date_str}.md"
        
        # 确保 reports 目录存在（使用项目根目录下的 reports）
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = reports_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"日报已保存到: {filepath}")
        return str(filepath)
