# -*- coding: utf-8 -*-
"""chat.py 纯函数单测。"""

import importlib
import os
import unittest
from unittest.mock import patch

import chat


_original_public_mode = chat._PUBLIC_MODE


def _reload_chat(env_overrides: dict):
    """重新加载 chat 模块以应用环境变量。"""
    with patch.dict(os.environ, env_overrides, clear=True):
        importlib.reload(chat)
    return chat


def _restore_chat():
    """恢复 chat 模块到原始状态。"""
    global _original_public_mode
    chat._PUBLIC_MODE = _original_public_mode


class TestIpBlocked(unittest.TestCase):
    """IP 地址过滤测试。"""

    def setUp(self):
        _restore_chat()

    def tearDown(self):
        _restore_chat()

    def test_metadata_ip_blocked(self):
        mod = _reload_chat({})
        self.assertTrue(mod._ip_blocked("169.254.1.1"))

    def test_localhost_blocked_in_public_mode(self):
        mod = _reload_chat({"VR_API_KEY": "test-key"})
        self.assertTrue(mod._ip_blocked("127.0.0.1"))

    def test_localhost_allowed_in_local_mode(self):
        mod = _reload_chat({})
        self.assertFalse(mod._ip_blocked("127.0.0.1"))

    def test_private_ip_blocked_in_public_mode(self):
        mod = _reload_chat({"VR_API_KEY": "test-key"})
        self.assertTrue(mod._ip_blocked("10.0.0.1"))
        self.assertTrue(mod._ip_blocked("172.16.0.1"))
        self.assertTrue(mod._ip_blocked("192.168.1.1"))

    def test_private_ip_allowed_in_local_mode(self):
        mod = _reload_chat({})
        self.assertFalse(mod._ip_blocked("10.0.0.1"))
        self.assertFalse(mod._ip_blocked("172.16.0.1"))
        self.assertFalse(mod._ip_blocked("192.168.1.1"))

    def test_public_ip_allowed(self):
        mod = _reload_chat({"VR_API_KEY": "test-key"})
        self.assertFalse(mod._ip_blocked("8.8.8.8"))
        self.assertFalse(mod._ip_blocked("1.1.1.1"))

    def test_invalid_host_not_blocked(self):
        mod = _reload_chat({})
        self.assertFalse(mod._ip_blocked("example.com"))


class TestCheckBaseUrl(unittest.TestCase):
    """Base URL 检查测试。"""

    def setUp(self):
        _restore_chat()

    def tearDown(self):
        _restore_chat()

    def test_http_url_allowed(self):
        mod = _reload_chat({})
        mod._check_base_url("http://example.com")

    def test_https_url_allowed(self):
        mod = _reload_chat({})
        mod._check_base_url("https://example.com")

    def test_invalid_scheme_raises(self):
        mod = _reload_chat({})
        with self.assertRaises(RuntimeError):
            mod._check_base_url("ftp://example.com")

    def test_empty_url_raises(self):
        mod = _reload_chat({})
        with self.assertRaises(RuntimeError):
            mod._check_base_url("")

    def test_metadata_ip_raises(self):
        mod = _reload_chat({})
        with self.assertRaises(RuntimeError):
            mod._check_base_url("http://169.254.1.1")

    def test_private_ip_raises_in_public_mode(self):
        mod = _reload_chat({"VR_API_KEY": "test-key"})
        with self.assertRaises(RuntimeError):
            mod._check_base_url("http://192.168.1.1")


if __name__ == "__main__":
    unittest.main()
