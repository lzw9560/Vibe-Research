# -*- coding: utf-8 -*-
"""S101 飞书多点通知测试——9:25 竞价 / 9:35 开盘 / T+1 复盘。

契约（spec §3 R1-R18）：
- 3 executor：final=0 跳过不发 / 有数据发 + 内容断言 / NotificationService 不可用不崩
- 通知内容函数：格式 + §44 标签 + 逐只行
- seed：3 新 task 幂等创建（cron 9:25/9:35/16:35）
"""
from __future__ import annotations

import types

import scheduled_tasks as st


# ── 测试辅助 ───────────────────────────────────────────────────────────


def _mock_card(code: str, name: str = "") -> dict:
    return {"code": code, "name": name}


class _MockNS:
    """mock NotificationService——捕获 send() 调用内容。"""

    def __init__(self):
        self.sent: list[str] = []

    def is_available(self) -> bool:
        return True

    def send(self, content: str, **kwargs) -> bool:
        self.sent.append(content)
        return True


# ── 9:25 竞价确认通知 ─────────────────────────────────────────────────


class TestAuctionNotify:
    def test_no_candidates_skips_notify(self, monkeypatch):
        """final=0 → 不发通知（guard）。"""
        monkeypatch.setattr(st, "_load_final_cards", lambda f: [])
        mock_ns = _MockNS()
        monkeypatch.setattr(
            "notification.notification_service.NotificationService",
            lambda *a, **kw: mock_ns,
        )
        result = st.TaskExecutor()._execute_premarket_auction_notify({"date": "2026-08-21"})
        assert result["status"] == "ok"
        assert result["notified"] is False
        assert result["reason"] == "no_candidates"
        assert len(mock_ns.sent) == 0

    def test_sends_content_with_gap_pct(self, monkeypatch):
        """有候选 + quote → 发通知，内容含日期/逐只高开低开/§44 标签。"""
        monkeypatch.setattr(
            st, "_load_final_cards",
            lambda f: [_mock_card("600519", "贵州茅台"), _mock_card("000001", "平安银行")],
        )
        monkeypatch.setattr(st, "_fetch_quotes", lambda codes: {
            "600519": {"open": 1800.0, "last_close": 1780.0},
            "000001": {"open": 12.0, "last_close": 12.2},
        })
        mock_ns = _MockNS()
        monkeypatch.setattr(st, "_send_notify", lambda c: mock_ns.send(c) or True)

        result = st.TaskExecutor()._execute_premarket_auction_notify({"date": "2026-08-21"})
        assert result["status"] == "ok"
        assert result["notified"] is True
        assert result["candidates"] == 2
        content = mock_ns.sent[0]
        assert "2026-08-21" in content
        assert "贵州茅台" in content
        assert "高开" in content  # 1800 vs 1780 → 高开
        assert "低开" in content  # 12.0 vs 12.2 → 低开
        assert "§44" in content

    def test_notification_failure_does_not_crash(self, monkeypatch):
        """NotificationService 不可用 → notified=False，不崩（增强不阻断）。"""
        monkeypatch.setattr(st, "_load_final_cards", lambda f: [_mock_card("600519", "X")])
        monkeypatch.setattr(st, "_fetch_quotes", lambda codes: {})
        # NS 不可用 → _send_notify 返 False（不崩）
        monkeypatch.setattr(st, "_send_notify", lambda c: False)

        result = st.TaskExecutor()._execute_premarket_auction_notify({"date": "2026-08-21"})
        assert result["status"] == "ok"  # 不崩
        assert result["notified"] is False  # 不可用 → 未发


# ── 9:35 开盘表现通知 ──────────────────────────────────────────────────


class TestOpenNotify:
    def test_no_candidates_skips_notify(self, monkeypatch):
        monkeypatch.setattr(st, "_load_final_cards", lambda f: [])
        mock_ns = _MockNS()
        monkeypatch.setattr(st, "_send_notify", lambda c: mock_ns.send(c) or True)
        result = st.TaskExecutor()._execute_premarket_open_notify({"date": "2026-08-21"})
        assert result["notified"] is False
        assert len(mock_ns.sent) == 0

    def test_sends_content_with_seal_status(self, monkeypatch):
        """有候选 + quote → 内容含现价/涨跌幅/封板状态。"""
        monkeypatch.setattr(st, "_load_final_cards", lambda f: [
            _mock_card("600519", "贵州茅台"), _mock_card("000001", "封板票"),
        ])
        monkeypatch.setattr(st, "_fetch_quotes", lambda codes: {
            "600519": {"price": 1800.0, "change_pct": 1.15, "limit_up_price": 1958.0},
            "000001": {"price": 13.42, "change_pct": 10.0, "limit_up_price": 13.42},
        })
        mock_ns = _MockNS()
        monkeypatch.setattr(st, "_send_notify", lambda c: mock_ns.send(c) or True)

        result = st.TaskExecutor()._execute_premarket_open_notify({"date": "2026-08-21"})
        assert result["notified"] is True
        content = mock_ns.sent[0]
        assert "9:35" in content
        assert "贵州茅台" in content
        assert "未封板" in content  # 1800 < 1958
        assert "封板" in content  # 13.42 >= 13.42
        assert "§44" in content


# ── T+1 复盘通知 ──────────────────────────────────────────────────────


class TestT1Review:
    def test_no_candidates_skips_notify(self, monkeypatch):
        monkeypatch.setattr(st, "_load_final_cards", lambda f: [])
        mock_ns = _MockNS()
        monkeypatch.setattr(st, "_send_notify", lambda c: mock_ns.send(c) or True)
        result = st.TaskExecutor()._execute_premarket_t1_review({"date": "2026-08-21"})
        assert result["notified"] is False

    def test_sends_content_with_returns_and_44_note(self, monkeypatch):
        """有候选 + kline → 内容含均值/胜率/逐只 + §44 样本不足标注。"""
        monkeypatch.setattr(st, "_load_final_cards", lambda f: [
            _mock_card("600519", "贵州茅台"), _mock_card("000001", "平安银行"),
        ])
        monkeypatch.setattr(st, "_compute_t1_returns", lambda cards, f, t: [
            {"code": "600519", "name": "贵州茅台", "f_close": 100.0, "t_close": 105.0, "return_pct": 5.0},
            {"code": "000001", "name": "平安银行", "f_close": 10.0, "t_close": 9.5, "return_pct": -5.0},
        ])
        mock_ns = _MockNS()
        monkeypatch.setattr(st, "_send_notify", lambda c: mock_ns.send(c) or True)

        result = st.TaskExecutor()._execute_premarket_t1_review({"date": "2026-08-21"})
        assert result["notified"] is True
        content = mock_ns.sent[0]
        assert "T+1" in content
        assert "均值" in content
        assert "红盘" in content
        assert "样本不足" in content  # n=2 <30
        assert "不宣称 alpha" in content
        assert "贵州茅台" in content

    def test_large_sample_no_sample_warning(self, monkeypatch):
        """n>=30 → 不标样本不足。"""
        cards = [_mock_card(f"00000{i}", f"票{i}") for i in range(30)]
        returns = [{"code": f"00000{i}", "name": f"票{i}", "f_close": 10.0, "t_close": 10.5, "return_pct": 5.0} for i in range(30)]
        monkeypatch.setattr(st, "_load_final_cards", lambda f: cards)
        monkeypatch.setattr(st, "_compute_t1_returns", lambda c, f, t: returns)
        mock_ns = _MockNS()
        monkeypatch.setattr(st, "_send_notify", lambda c: mock_ns.send(c) or True)

        st.TaskExecutor()._execute_premarket_t1_review({"date": "2026-08-21"})
        content = mock_ns.sent[0]
        assert "样本不足" not in content
        assert "n=30" in content


# ── 内容构建函数 ──────────────────────────────────────────────────────


class TestContentBuilders:
    def test_auction_content_format(self):
        content = st._build_auction_notify_content(
            "2026-08-21",
            [_mock_card("600519", "茅台")],
            {"600519": {"open": 10.0, "last_close": 9.9}},
        )
        assert "9:25" in content
        assert "2026-08-21" in content
        assert "茅台" in content
        assert "高开" in content
        assert "§44" in content

    def test_open_content_missing_quote(self):
        """quote 缺 → 标'行情待接入'不崩。"""
        content = st._build_open_notify_content(
            "2026-08-21", [_mock_card("600519", "茅台")], {},
        )
        assert "行情待接入" in content
        assert "§44" in content

    def test_t1_empty_returns(self):
        content = st._build_t1_review_content("2026-08-21", "2026-08-22", [])
        assert "无 T+1 收益数据" in content
        assert "§44" in content

    def test_fmt_pct_none(self):
        assert st._fmt_pct(None) == "—"
        assert "5.00%" in st._fmt_pct(5.0)
        assert "-" in st._fmt_pct(-3.5)


# ── seed 幂等 ──────────────────────────────────────────────────────────


class TestSeed:
    def test_three_new_tasks_seeded(self):
        """_ensure_seed_tasks 后 3 个新 task 在 DB（幂等，重复跑不重复创建）。"""
        st._ensure_seed_tasks()
        names = {t.name: t for t in st._manager.list_tasks()}
        for name, cron in [
            ("premarket_auction_notify", "25 9 * * 0-4"),
            ("premarket_open_notify", "35 9 * * 0-4"),
            ("premarket_t1_review", "35 16 * * 0-4"),
        ]:
            assert name in names, f"{name} 未 seed"
            assert names[name].cron_expr == cron, f"{name} cron={names[name].cron_expr}"
            assert names[name].enabled is True
        # 幂等：再跑一次不重复
        before = len(st._manager.list_tasks())
        st._ensure_seed_tasks()
        after = len(st._manager.list_tasks())
        assert before == after
