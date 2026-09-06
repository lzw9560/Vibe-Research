# -*- coding: utf-8 -*-
"""S164 R4：Secrets gate —— 启动时密钥健康度校验。

启动时非阻塞校验（只 log warning，不阻断服务）：
1. ``.env`` 在 ``.gitignore`` 中（防密钥泄漏到 git）。
2. ``HITHINK_FINANCE_API_KEY`` 存在 + 非泄漏标记（``sk-fuyaro-`` 前缀 =
   用户待轮换的泄漏 key，CLAUDE.md memory 记录）。
3. ``VR_LLM_API_KEY`` 存在（缺失 → info 级提示，不阻断）。

hithink key 轮换是用户 TODO（revoke 泄漏 key + 重生成写 .env，不贴对话）。
本模块只做检测 + 提醒，不修改任何密钥或阻断启动。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("vibe-research")

# 泄漏 key 标记（CLAUDE.md memory hithink-apikey-泄漏待轮换：sk-fuyaro- 前缀）
_LEAKED_KEY_MARKER = "sk-fuyaro-"


def _check_env_gitignore() -> list[str]:
    """检查 .env 在 .gitignore 中（防密钥泄漏到 git）。"""
    warnings: list[str] = []
    repo_root = Path(__file__).resolve().parent.parent
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        warnings.append(".gitignore 不存在——密钥可能泄漏到 git")
        return warnings
    content = gitignore.read_text(encoding="utf-8")
    # 检查 .env 模式（行首 .env 或独立行 .env）
    lines = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    has_env = any(ln == ".env" or ln.startswith(".env") for ln in lines)
    if not has_env:
        warnings.append(".env 未在 .gitignore 中——密钥可能泄漏到 git")
    return warnings


def _check_hithink_key() -> list[str]:
    """检查 hithink API key 健康度。"""
    warnings: list[str] = []
    key = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
    if not key:
        warnings.append(
            "HITHINK_FINANCE_API_KEY 未设置——hithink 估值(PS/PCF)/异动/涨停池数据将不可用"
        )
    elif _LEAKED_KEY_MARKER in key:
        warnings.append(
            "HITHINK_FINANCE_API_KEY 疑似泄漏 key（sk-fuyaro- 前缀）——"
            "请立即去 fuyao.aicubes.cn/admin revoke 并重新生成，写入 .env（不贴对话）"
        )
    return warnings


def _check_llm_key() -> list[str]:
    """检查 VR_LLM_API_KEY（缺失只 info 级提示，不阻断）。"""
    warnings: list[str] = []
    key = os.environ.get("VR_LLM_API_KEY", "").strip()
    base_url = os.environ.get("VR_LLM_BASE_URL", "").strip()
    if not key and base_url:
        warnings.append(
            "VR_LLM_BASE_URL 已设但 VR_LLM_API_KEY 未设——AI 对话/预测功能将不可用"
        )
    return warnings


def validate() -> dict:
    """执行所有密钥健康度校验。非阻塞（只 log warning）。

    返回 ``{"ok": True, "warnings": [...]}``。ok 恒 True（不阻断启动），
    warnings 为提示列表（空列表 = 全部健康）。
    """
    warnings: list[str] = []
    warnings.extend(_check_env_gitignore())
    warnings.extend(_check_hithink_key())
    warnings.extend(_check_llm_key())

    for w in warnings:
        logger.warning("[secrets_gate] %s", w)

    if not warnings:
        logger.info("[secrets_gate] 密钥健康度校验通过（.env gitignore + hithink key + LLM key）")

    return {"ok": True, "warnings": warnings}
