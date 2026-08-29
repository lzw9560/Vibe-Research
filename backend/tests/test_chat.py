# -*- coding: utf-8 -*-
"""chat.py 纯函数单测。"""

import os
import unittest
from unittest.mock import patch

import chat


def _restore_chat():
    """恢复 chat 模块到默认状态（_is_public_mode 读环境变量）。"""
    pass  # _is_public_mode 动态读取，无需手动恢复


class TestIpBlocked(unittest.TestCase):
    """IP 地址过滤测试。"""

    def setUp(self):
        _restore_chat()

    def tearDown(self):
        _restore_chat()

    def test_metadata_ip_blocked(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(chat._ip_blocked("169.254.1.1"))

    def test_localhost_blocked_in_public_mode(self):
        with patch.dict(os.environ, {"VR_API_KEY": "test-key"}, clear=True):
            self.assertTrue(chat._ip_blocked("127.0.0.1"))

    def test_localhost_allowed_in_local_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(chat._ip_blocked("127.0.0.1"))

    def test_private_ip_blocked_in_public_mode(self):
        with patch.dict(os.environ, {"VR_API_KEY": "test-key"}, clear=True):
            self.assertTrue(chat._ip_blocked("10.0.0.1"))
            self.assertTrue(chat._ip_blocked("172.16.0.1"))
            self.assertTrue(chat._ip_blocked("192.168.1.1"))

    def test_private_ip_allowed_in_local_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(chat._ip_blocked("10.0.0.1"))
            self.assertFalse(chat._ip_blocked("172.16.0.1"))
            self.assertFalse(chat._ip_blocked("192.168.1.1"))

    def test_public_ip_allowed(self):
        with patch.dict(os.environ, {"VR_API_KEY": "test-key"}, clear=True):
            self.assertFalse(chat._ip_blocked("8.8.8.8"))
            self.assertFalse(chat._ip_blocked("1.1.1.1"))

    def test_invalid_host_not_blocked(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(chat._ip_blocked("example.com"))


class TestCheckBaseUrl(unittest.TestCase):
    """Base URL 检查测试。"""

    def setUp(self):
        _restore_chat()

    def tearDown(self):
        _restore_chat()

    def test_http_url_allowed(self):
        with patch.dict(os.environ, {}, clear=True):
            chat._check_base_url("http://example.com")

    def test_https_url_allowed(self):
        with patch.dict(os.environ, {}, clear=True):
            chat._check_base_url("https://example.com")

    def test_invalid_scheme_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                chat._check_base_url("ftp://example.com")

    def test_empty_url_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                chat._check_base_url("")

    def test_metadata_ip_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                chat._check_base_url("http://169.254.1.1")

    def test_private_ip_raises_in_public_mode(self):
        with patch.dict(os.environ, {"VR_API_KEY": "test-key"}, clear=True):
            with self.assertRaises(RuntimeError):
                chat._check_base_url("http://192.168.1.1")


class TestGetEnvLLMConfig(unittest.TestCase):
    """S001: chat._get_env_llm_config 读环境变量兜底配置，返回三键 dict（缺省空串）。"""

    _ENV = {
        "VR_LLM_BASE_URL": "https://api.deepseek.com/v1",
        "VR_LLM_API_KEY": "sk-test-redacted",
        "VR_LLM_MODEL": "deepseek-chat",
    }

    def test_returns_three_keys_with_values(self):
        with patch.dict(os.environ, self._ENV, clear=False):
            cfg = chat._get_env_llm_config()
        self.assertEqual(cfg["baseURL"], "https://api.deepseek.com/v1")
        self.assertEqual(cfg["apiKey"], "sk-test-redacted")
        self.assertEqual(cfg["model"], "deepseek-chat")

    def test_missing_vars_default_to_empty_string(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = chat._get_env_llm_config()
        self.assertEqual(cfg, {"baseURL": "", "apiKey": "", "model": ""})

    def test_partial_vars_partial_fill(self):
        only_model = {"VR_LLM_MODEL": "deepseek-chat"}
        with patch.dict(os.environ, only_model, clear=True):
            cfg = chat._get_env_llm_config()
        self.assertEqual(cfg["baseURL"], "")
        self.assertEqual(cfg["apiKey"], "")
        self.assertEqual(cfg["model"], "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
