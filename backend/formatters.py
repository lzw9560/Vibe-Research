# -*- coding: utf-8 -*-
"""通知模块使用的格式化工具函数。"""

from __future__ import annotations

import re
from typing import List, Optional

# 常量
MIN_MAX_BYTES = 4000
PAGE_MARKER_SAFE_BYTES = 200
MIN_MAX_WORDS = 3500


def chunk_content_by_max_bytes(content: str, max_bytes: int = MIN_MAX_BYTES) -> List[str]:
    """按字节数切分内容。"""
    if not content:
        return [""]
    chunks = []
    current = ""
    for line in content.split("\n"):
        test = current + "\n" + line if current else line
        if len(test.encode("utf-8")) > max_bytes:
            if current:
                chunks.append(current)
            current = line
        else:
            current = test
    if current:
        chunks.append(current)
    return chunks or [""]


def chunk_content_by_max_words(content: str, max_words: int = MIN_MAX_WORDS) -> List[str]:
    """按词数切分内容。"""
    if not content:
        return [""]
    words = content.split()
    chunks = []
    current_words = []
    for word in words:
        current_words.append(word)
        if len(current_words) >= max_words:
            chunks.append(" ".join(current_words))
            current_words = []
    if current_words:
        chunks.append(" ".join(current_words))
    return chunks or [""]


def slice_at_max_bytes(content: str, max_bytes: int = MIN_MAX_BYTES) -> str:
    """截断内容到最大字节数。"""
    if not content:
        return ""
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated


def markdown_to_plain_text(markdown: str) -> str:
    """简单 Markdown 转纯文本。"""
    text = re.sub(r'#{1,6}\s+', '', markdown)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '', text)
    text = re.sub(r'[-*_]{3,}', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def markdown_to_html_document(markdown: str) -> str:
    """简单 Markdown 转 HTML。"""
    html = markdown
    html = re.sub(r'#{1,6}\s+(.*)', r'<h>\1</h>', html)
    html = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'<b>\1</b>', html)
    html = re.sub(r'`{1,3}([^`]*)`{1,3}', r'<code>\1</code>', html)
    html = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'<a href="\2">\1</a>', html)
    html = html.replace('\n', '<br/>')
    return f"<html><body>{html}</body></html>"


def format_feishu_markdown(content: str) -> str:
    """格式化飞书 Markdown。"""
    text = markdown_to_plain_text(content)
    if len(text) > 4000:
        text = text[:4000] + "..."
    return text
