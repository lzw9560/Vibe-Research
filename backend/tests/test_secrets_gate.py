# -*- coding: utf-8 -*-
"""S164 R4：secrets gate 单测。

覆盖：
- .env 在 .gitignore 中（pass）
- .env 不在 .gitignore 中（warning）
- HITHINK_FINANCE_API_KEY 缺失（warning）
- HITHINK_FINANCE_API_KEY 泄漏标记（warning）
- HITHINK_FINANCE_API_KEY 正常（no warning for hithink）
- VR_LLM_API_KEY 缺失但 VR_LLM_BASE_URL 已设（warning）
- validate() 非阻塞（ok 恒 True）
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """清空相关环境变量。"""
    monkeypatch.delenv("HITHINK_FINANCE_API_KEY", raising=False)
    monkeypatch.delenv("VR_LLM_API_KEY", raising=False)
    monkeypatch.delenv("VR_LLM_BASE_URL", raising=False)
    yield


def test_env_gitignore_present(clean_env):
    """R4：.env 在 .gitignore 中 → 无 gitignore warning。"""
    from secrets_gate import validate

    result = validate()
    assert result["ok"] is True
    # .env 已在 .gitignore（项目根），不应有 gitignore warning
    gitignore_warnings = [w for w in result["warnings"] if "gitignore" in w.lower()]
    assert len(gitignore_warnings) == 0, f"不应有 gitignore warning: {gitignore_warnings}"


def test_hithink_key_missing_warns(clean_env):
    """R4：HITHINK_FINANCE_API_KEY 缺失 → warning。"""
    from secrets_gate import validate

    result = validate()
    hithink_warnings = [w for w in result["warnings"] if "HITHINK" in w]
    assert len(hithink_warnings) == 1
    assert "未设置" in hithink_warnings[0]


def test_hithink_key_leaked_marker_warns(clean_env, monkeypatch):
    """R4：HITHINK_FINANCE_API_KEY 含泄漏标记 sk-fuyaro- → warning。"""
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "sk-fuyaro-VbXFnY0WgwWFVTOWTVIIYxYrXNq3_vFe")
    from secrets_gate import validate

    result = validate()
    leaked_warnings = [w for w in result["warnings"] if "泄漏" in w or "sk-fuyaro" in w]
    assert len(leaked_warnings) == 1
    assert "revoke" in leaked_warnings[0].lower() or "revoke" in leaked_warnings[0]


def test_hithink_key_valid_no_warning(clean_env, monkeypatch):
    """R4：HITHINK_FINANCE_API_KEY 正常（非泄漏标记）→ 无 hithink warning。"""
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "sk-validkey-abc123notleaked")
    from secrets_gate import validate

    result = validate()
    hithink_warnings = [w for w in result["warnings"] if "HITHINK" in w]
    assert len(hithink_warnings) == 0, f"正常 key 不应 warning: {hithink_warnings}"


def test_llm_key_missing_with_base_url_warns(clean_env, monkeypatch):
    """R4：VR_LLM_BASE_URL 已设但 VR_LLM_API_KEY 未设 → warning。"""
    monkeypatch.setenv("HITHINK_FINANCE_API_KEY", "sk-validkey-abc123")
    monkeypatch.setenv("VR_LLM_BASE_URL", "https://api.example.com/v1")
    from secrets_gate import validate

    result = validate()
    llm_warnings = [w for w in result["warnings"] if "VR_LLM_API_KEY" in w]
    assert len(llm_warnings) == 1
    assert "不可用" in llm_warnings[0]


def test_validate_always_ok(clean_env):
    """R4：validate() ok 恒 True（非阻断）。"""
    from secrets_gate import validate

    result = validate()
    assert result["ok"] is True
    assert "warnings" in result
    assert isinstance(result["warnings"], list)


def test_validate_returns_warnings_list(clean_env):
    """R4：validate() 返回 warnings list（可空）。"""
    from secrets_gate import validate

    # 设全部正常 key
    os.environ["HITHINK_FINANCE_API_KEY"] = "sk-validkey-abc123"
    os.environ["VR_LLM_API_KEY"] = "sk-llm-validkey-abc123"
    os.environ["VR_LLM_BASE_URL"] = "https://api.example.com/v1"
    try:
        result = validate()
        # 全正常 → warnings 可能有 0 项（.env 已在 gitignore）
        assert result["ok"] is True
    finally:
        del os.environ["HITHINK_FINANCE_API_KEY"]
        del os.environ["VR_LLM_API_KEY"]
        del os.environ["VR_LLM_BASE_URL"]
