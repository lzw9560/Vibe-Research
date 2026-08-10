# -*- coding: utf-8 -*-
"""S015 R2 —— config 类型校验：_parse_bool/_parse_int/_parse_float 失败告警不静默。"""
from __future__ import annotations

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402


def test_parse_bool_true_values():
    for v in ("true", "1", "yes", "on", "TRUE", "Yes"):
        assert config._parse_bool("K", v, False) is True


def test_parse_bool_false_values():
    for v in ("false", "0", "no", "off", "False"):
        assert config._parse_bool("K", v, True) is False


def test_parse_bool_invalid_warns_and_defaults(caplog):
    with caplog.at_level(logging.WARNING, logger="vibe-research.config"):
        result = config._parse_bool("K", "maybe", True)
    assert result is True
    assert any("无效 bool" in m for m in caplog.messages)


def test_parse_bool_none_returns_default():
    assert config._parse_bool("K", None, True) is True
    assert config._parse_bool("K", None, False) is False


def test_parse_int_valid():
    assert config._parse_int("K", "42", 0) == 42


def test_parse_int_invalid_warns_and_defaults(caplog):
    with caplog.at_level(logging.WARNING, logger="vibe-research.config"):
        result = config._parse_int("K", "abc", 7)
    assert result == 7
    assert any("无效 int" in m for m in caplog.messages)


def test_parse_int_none_returns_default():
    assert config._parse_int("K", None, 5) == 5


def test_parse_float_invalid_warns_and_defaults(caplog):
    with caplog.at_level(logging.WARNING, logger="vibe-research.config"):
        result = config._parse_float("K", "n/a", 1.5)
    assert result == 1.5
    assert any("无效 float" in m for m in caplog.messages)


def test_load_config_invalid_env_does_not_raise(monkeypatch):
    """非法环境变量不应让 load_config 崩溃；告警并沿用默认。"""
    monkeypatch.setenv("VR_CONCURRENT_REQUESTS", "not-an-int")
    monkeypatch.setenv("VR_GENE_QUALIFY_THRESHOLD", "not-a-float")
    cfg = config.load_config()
    # 非法值 → 保留 dataclass 默认
    assert cfg.CONCURRENT_REQUESTS == 10
    assert cfg.GENE_QUALIFY_THRESHOLD == 50.0
