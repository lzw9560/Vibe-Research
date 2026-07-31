# -*- coding: utf-8 -*-
"""cli_runtime 回归测试（离线，不导入 app）。

锁住「订阅 CLI 接入」路径的关键不变量：
- run_cli_stream/run_cli 必须以 encoding=utf-8 起子进程（Windows cp936 本机 locale
  下 text=True 不指定 encoding 会用 GBK 解码 claude.CMD 的 UTF-8 stdout →
  UnicodeDecodeError 被 _pump 的 bare except 吞掉 → 静默零输出，见 HIGH-5 修订）。
"""

from __future__ import annotations

import subprocess
import unittest
from unittest import mock

import cli_runtime


class _FakeStdin:
    def write(self, _s): pass
    def close(self): pass


class _FakeProc:
    returncode = 0
    stdin = _FakeStdin()
    stdout = iter(["hello\n"])

    def wait(self, timeout=None): return 0
    def kill(self): pass
    def poll(self): return 0


class TestRunCliStreamEncoding(unittest.TestCase):
    """run_cli_stream 必须以 encoding=utf-8 / errors=replace 起 CLI 子进程。"""

    def test_popen_called_with_utf8_encoding(self):
        captured = {}

        def fake_popen(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProc()

        with mock.patch.object(cli_runtime, "detect_cli", lambda kind: "/fake/fake-bin"), \
             mock.patch.object(cli_runtime.subprocess, "Popen", fake_popen), \
             mock.patch.dict(cli_runtime._CLI_DEFS, {
                 "fake": {"bins": ["fake-bin"], "delivery": "stdin",
                          "build_args": lambda _: [], "env": {}},
             }, clear=False):
            chunks = list(cli_runtime.run_cli_stream("fake", "sys", "user"))

        self.assertEqual(chunks, ["hello\n"])
        self.assertEqual(captured.get("encoding"), "utf-8")
        self.assertEqual(captured.get("errors"), "replace")
        self.assertTrue(captured.get("text"))


if __name__ == "__main__":
    unittest.main()
