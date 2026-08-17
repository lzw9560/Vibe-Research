# -*- coding: utf-8 -*-
"""S075 首板流·大盘3因素精筛 + 飞书通知单测（tasks.md 041-042）。

覆盖：
- 041 3因素组合判定（judge_market_env）
    - 绿灯：hs300>0.5% OR zt_ratio>0.5 OR max_boards≥4（任一绿即绿）
    - 黄灯：其他（未达绿也未达红）
    - 红灯：hs300<-0.5% AND zt_ratio<0.3 AND max_boards≤2（全红才红）
    - 仓位建议（绿灯3-5只/黄灯最多3只15%/红灯不建仓）
- 042 红灯人工override + 数据缺失降级 + 飞书通知
    - 全部因素缺失 → 黄灯（中性，不误判红灯）
    - 一绿+缺失 → 绿灯（任一绿即绿）
    - 一红+缺失 → 黄灯（不满足全红，数据缺失不误判红灯）
    - max_boards T-1 fallback 标注 is_t1_fallback=True
    - 红灯触发飞书通知 / 绿灯不推 / 未配通道不崩

mock 模式（参考 test_s075_first_board_filter.py）：
- 顶部 `from astock import em_zt_topic_pool, index_quote` 绑定到本模块属性
  → patch `strategies.first_board_market_env.index_quote` 等
- `from market import _emotion` 同样绑定到本模块属性
- `notify_market_env` 内函数体懒导入 `NotificationService`
  → patch `notification.notification_service.NotificationService` 类方法

纯 mock 无网络。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# =========================================================================
# 公共 mock 数据工厂
# =========================================================================

def _make_zt_compare(
    zt_count_t1: int = 10,
    zt_count_t: int | None = 5,
    ratio: float | None = 0.5,
    note: str = "",
) -> dict:
    """构造 fetch_zt_count_compare 返回结构。"""
    return {
        "zt_count_t1": zt_count_t1,
        "zt_count_t": zt_count_t,
        "ratio": ratio,
        "note": note,
    }


def _make_max_boards_data(
    max_boards: int | None = 3,
    source_date: str = "2026-08-18",
    is_t1_fallback: bool = False,
    note: str = "",
) -> dict:
    """构造 fetch_max_boards 返回结构。"""
    return {
        "max_boards": max_boards,
        "source_date": source_date,
        "is_t1_fallback": is_t1_fallback,
        "note": note,
    }


# =========================================================================
# 041 3因素组合判定
# =========================================================================

class TestJudgeMarketEnv:
    """041：测试 judge_market_env（3因素组合判定）。"""

    # ── 绿灯：任一绿即绿 ────────────────────────────────────────────────

    def test_green_light_hs300_only(self):
        """绿灯触发1：hs300 单因素绿（hs300=1.0% > 0.5%）→ 绿灯。"""
        from strategies.first_board_market_env import judge_market_env
        # hs300=1.0% 绿；zt_ratio=0.4 黄；max_boards=3 黄
        result = judge_market_env(
            hs300_pct=1.0,
            zt_compare=_make_zt_compare(ratio=0.4),
            max_boards_data=_make_max_boards_data(max_boards=3),
        )
        assert result["light"] == "green"
        assert result["factors"]["hs300"] == "green"
        assert result["factors"]["zt_count"] == "yellow"
        assert result["factors"]["max_boards"] == "yellow"

    def test_green_light_zt_ratio_only(self):
        """绿灯触发2：zt_ratio 单因素绿（ratio=0.6 > 0.5）→ 绿灯。"""
        from strategies.first_board_market_env import judge_market_env
        # hs300=0.2% 黄；zt_ratio=0.6 绿；max_boards=3 黄
        result = judge_market_env(
            hs300_pct=0.2,
            zt_compare=_make_zt_compare(ratio=0.6),
            max_boards_data=_make_max_boards_data(max_boards=3),
        )
        assert result["light"] == "green"
        assert result["factors"]["zt_count"] == "green"

    def test_green_light_max_boards_only(self):
        """绿灯触发3：max_boards 单因素绿（max_boards=4 ≥ 4）→ 绿灯。"""
        from strategies.first_board_market_env import judge_market_env
        # hs300=0.2% 黄；zt_ratio=0.4 黄；max_boards=4 绿
        result = judge_market_env(
            hs300_pct=0.2,
            zt_compare=_make_zt_compare(ratio=0.4),
            max_boards_data=_make_max_boards_data(max_boards=4),
        )
        assert result["light"] == "green"
        assert result["factors"]["max_boards"] == "green"

    # ── 黄灯：未达绿也未达红 ────────────────────────────────────────────

    def test_yellow_light(self):
        """黄灯：三因素都未达绿也未达红（hs300=0.2%, zt_ratio=0.4, max_boards=3）。"""
        from strategies.first_board_market_env import judge_market_env
        result = judge_market_env(
            hs300_pct=0.2,
            zt_compare=_make_zt_compare(ratio=0.4),
            max_boards_data=_make_max_boards_data(max_boards=3),
        )
        assert result["light"] == "yellow"
        assert all(v == "yellow" for v in result["factors"].values())

    # ── 红灯：全红才红 ──────────────────────────────────────────────────

    def test_red_light(self):
        """红灯：hs300<-0.5% AND zt_ratio<0.3 AND max_boards≤2 → 红灯。"""
        from strategies.first_board_market_env import judge_market_env
        # hs300=-1.0% 红；zt_ratio=0.2 红；max_boards=2 红
        result = judge_market_env(
            hs300_pct=-1.0,
            zt_compare=_make_zt_compare(ratio=0.2),
            max_boards_data=_make_max_boards_data(max_boards=2),
        )
        assert result["light"] == "red"
        assert all(v == "red" for v in result["factors"].values())

    # ── 仓位建议 ──────────────────────────────────────────────────────

    def test_position_advice_green(self):
        """绿灯仓位建议：3-5只等权20-33%。"""
        from strategies.first_board_market_env import judge_market_env
        result = judge_market_env(
            hs300_pct=1.0,
            zt_compare=_make_zt_compare(ratio=0.6),
            max_boards_data=_make_max_boards_data(max_boards=5),
        )
        assert result["light"] == "green"
        advice = result["position_advice"]
        assert "3-5只" in advice
        assert "等权" in advice

    def test_position_advice_yellow(self):
        """黄灯仓位建议：最多3只单股15%。"""
        from strategies.first_board_market_env import judge_market_env
        result = judge_market_env(
            hs300_pct=0.2,
            zt_compare=_make_zt_compare(ratio=0.4),
            max_boards_data=_make_max_boards_data(max_boards=3),
        )
        assert result["light"] == "yellow"
        advice = result["position_advice"]
        assert "最多3只" in advice
        assert "15%" in advice

    def test_position_advice_red(self):
        """红灯仓位建议：不建仓。"""
        from strategies.first_board_market_env import judge_market_env
        result = judge_market_env(
            hs300_pct=-1.0,
            zt_compare=_make_zt_compare(ratio=0.2),
            max_boards_data=_make_max_boards_data(max_boards=2),
        )
        assert result["light"] == "red"
        advice = result["position_advice"]
        assert "不建仓" in advice


# =========================================================================
# 042 数据缺失降级 + 红灯人工override + 飞书通知
# =========================================================================

class TestDataMissingDegradation:
    """042：数据缺失降级 + 红灯人工override + 飞书通知。"""

    def test_all_factors_missing_returns_yellow(self):
        """全部因素缺失 → 黄灯（中性，不误判红灯）。

        hs300_pct=None, zt_compare 全空, max_boards_data 全空
        → 三因素都标 yellow → light=yellow
        """
        from strategies.first_board_market_env import judge_market_env
        result = judge_market_env(
            hs300_pct=None,
            zt_compare={},
            max_boards_data={},
        )
        assert result["light"] == "yellow"
        assert result["factors"]["hs300"] == "yellow"
        assert result["factors"]["zt_count"] == "yellow"
        assert result["factors"]["max_boards"] == "yellow"

    def test_one_green_with_missing_returns_green(self):
        """一绿+缺失 → 绿灯（任一绿即绿）。

        hs300=1.0%（绿），zt_compare 空（缺失），max_boards_data 空（缺失）
        → light=green（数据缺失不影响绿判定）
        """
        from strategies.first_board_market_env import judge_market_env
        result = judge_market_env(
            hs300_pct=1.0,
            zt_compare={},
            max_boards_data={},
        )
        assert result["light"] == "green"
        assert result["factors"]["hs300"] == "green"
        assert result["factors"]["zt_count"] == "yellow"
        assert result["factors"]["max_boards"] == "yellow"

    def test_one_red_with_missing_returns_yellow(self):
        """一红+缺失 → 黄灯（不满足全红，数据缺失不误判红灯）。

        hs300=-1.0%（红），其余因素缺失（yellow）→ 不能判红，判黄
        """
        from strategies.first_board_market_env import judge_market_env
        result = judge_market_env(
            hs300_pct=-1.0,
            zt_compare={},
            max_boards_data={},
        )
        assert result["light"] == "yellow"
        assert result["factors"]["hs300"] == "red"
        # 其余因素缺失 → yellow
        assert result["factors"]["zt_count"] == "yellow"
        assert result["factors"]["max_boards"] == "yellow"

    # ── max_boards T-1 fallback ────────────────────────────────────────

    def test_max_boards_t1_fallback_flagged(self, monkeypatch):
        """max_boards T-1 fallback：T日 _emotion 返空 → 取 T-1，is_t1_fallback=True。"""
        from strategies import first_board_market_env as m

        # mock T日 _emotion 返空 dict → 触发降级取 T-1
        # mock T-1 _emotion 返正常情绪（max_boards=3）
        call_log: list[str] = []

        def fake_emotion(date: str) -> dict:
            call_log.append(date)
            # 第一次调用（T日 2026-08-18）返空 → 触发降级
            if date == "2026-08-18":
                return {}
            # T-1 2026-08-17 返正常
            if date == "2026-08-17":
                return {"max_boards": 3, "ladder": [{"boards": 2, "count": 5}]}
            return {}

        monkeypatch.setattr(m, "_emotion", fake_emotion)

        result = m.fetch_max_boards("20260818")
        # T-1 fallback 触发
        assert result["is_t1_fallback"] is True
        assert result["max_boards"] == 3
        assert result["source_date"] == "2026-08-17"
        # 验证两次调用（T日 + T-1）
        assert "2026-08-18" in call_log
        assert "2026-08-17" in call_log

    def test_max_boards_no_fallback_when_t_has_data(self, monkeypatch):
        """T日 _emotion 返正常数据 → 不降级，is_t1_fallback=False。"""
        from strategies import first_board_market_env as m

        def fake_emotion(date: str) -> dict:
            if date == "2026-08-18":
                return {"max_boards": 4, "ladder": [{"boards": 3, "count": 2}]}
            return {}

        monkeypatch.setattr(m, "_emotion", fake_emotion)

        result = m.fetch_max_boards("20260818")
        assert result["is_t1_fallback"] is False
        assert result["max_boards"] == 4
        assert result["source_date"] == "2026-08-18"

    # ── 飞书通知 ──────────────────────────────────────────────────────

    def test_notify_red_light_pushes(self, monkeypatch):
        """红灯触发飞书通知。"""
        from strategies import first_board_market_env as m

        # 构造红灯结果
        result = {
            "date": "20260818",
            "hs300_pct": -1.0,
            "zt_compare": _make_zt_compare(zt_count_t1=10, zt_count_t=2, ratio=0.2),
            "max_boards_data": _make_max_boards_data(max_boards=2),
            "judge": m.judge_market_env(
                hs300_pct=-1.0,
                zt_compare=_make_zt_compare(ratio=0.2),
                max_boards_data=_make_max_boards_data(max_boards=2),
            ),
            "notified": False,
        }
        assert result["judge"]["light"] == "red"

        # mock NotificationService
        call_log: list = []

        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return True

            def send(self, content, route_type=None, severity=None, **kw) -> bool:
                call_log.append({
                    "content": content,
                    "route_type": route_type,
                    "severity": severity,
                })
                return True

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        notified = m.notify_market_env(result)
        assert notified is True
        assert len(call_log) == 1
        # 红灯 severity=warning
        assert call_log[0]["severity"] == "warning"
        assert call_log[0]["route_type"] == "alert"

    def test_notify_yellow_light_pushes_info(self, monkeypatch):
        """黄灯也推送，但 severity=info（红灯warning，黄灯info）。"""
        from strategies import first_board_market_env as m

        result = {
            "date": "20260818",
            "hs300_pct": 0.2,
            "zt_compare": _make_zt_compare(ratio=0.4),
            "max_boards_data": _make_max_boards_data(max_boards=3),
            "judge": m.judge_market_env(
                hs300_pct=0.2,
                zt_compare=_make_zt_compare(ratio=0.4),
                max_boards_data=_make_max_boards_data(max_boards=3),
            ),
            "notified": False,
        }
        assert result["judge"]["light"] == "yellow"

        call_log: list = []

        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return True

            def send(self, content, route_type=None, severity=None, **kw) -> bool:
                call_log.append({"severity": severity, "route_type": route_type})
                return True

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        notified = m.notify_market_env(result)
        assert notified is True
        assert call_log[0]["severity"] == "info"

    def test_notify_green_light_no_push(self, monkeypatch):
        """绿灯不推送（不打扰）。"""
        from strategies import first_board_market_env as m

        result = {
            "date": "20260818",
            "hs300_pct": 1.0,
            "zt_compare": _make_zt_compare(ratio=0.6),
            "max_boards_data": _make_max_boards_data(max_boards=5),
            "judge": m.judge_market_env(
                hs300_pct=1.0,
                zt_compare=_make_zt_compare(ratio=0.6),
                max_boards_data=_make_max_boards_data(max_boards=5),
            ),
            "notified": False,
        }
        assert result["judge"]["light"] == "green"

        send_called = [False]

        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return True

            def send(self, *a, **kw) -> bool:
                send_called[0] = True
                return True

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        notified = m.notify_market_env(result)
        assert notified is False
        assert send_called[0] is False  # send 未被调用

    def test_notify_no_channel_available(self, monkeypatch):
        """未配通道时 is_available()=False，不崩，notified=False。"""
        from strategies import first_board_market_env as m

        result = {
            "date": "20260818",
            "hs300_pct": -1.0,
            "zt_compare": _make_zt_compare(ratio=0.2),
            "max_boards_data": _make_max_boards_data(max_boards=2),
            "judge": m.judge_market_env(
                hs300_pct=-1.0,
                zt_compare=_make_zt_compare(ratio=0.2),
                max_boards_data=_make_max_boards_data(max_boards=2),
            ),
            "notified": False,
        }
        assert result["judge"]["light"] == "red"

        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return False  # 无可用渠道

            def send(self, *a, **kw) -> bool:  # pragma: no cover
                raise AssertionError("不应调用 send")

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        # 不抛异常
        notified = m.notify_market_env(result)
        assert notified is False

    def test_notify_send_exception_returns_false(self, monkeypatch):
        """send 抛异常时不崩，notified=False。"""
        from strategies import first_board_market_env as m

        result = {
            "date": "20260818",
            "hs300_pct": -1.0,
            "zt_compare": _make_zt_compare(ratio=0.2),
            "max_boards_data": _make_max_boards_data(max_boards=2),
            "judge": m.judge_market_env(
                hs300_pct=-1.0,
                zt_compare=_make_zt_compare(ratio=0.2),
                max_boards_data=_make_max_boards_data(max_boards=2),
            ),
            "notified": False,
        }

        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return True

            def send(self, *a, **kw) -> bool:
                raise RuntimeError("飞书接口故障")

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        notified = m.notify_market_env(result)
        assert notified is False


# =========================================================================
# 端到端
# =========================================================================

class TestRunMarketEnvCheck:
    """端到端：mock 全部数据源，验证返回结构完整。"""

    def test_end_to_end_structure(self, monkeypatch):
        """端到端：mock index_quote / em_zt_topic_pool / _emotion / NotificationService。"""
        from strategies import first_board_market_env as m

        # 034 mock index_quote 返沪深300 +0.8%（绿灯因素）
        monkeypatch.setattr(
            m, "index_quote",
            lambda: [{"name": "沪深300", "change_pct": 0.8}],
        )

        # 035 mock em_zt_topic_pool
        # T日竞价涨停 8 家，T-1 全天 10 家 → ratio=0.8（绿灯因素）
        def fake_pool(*a, **kw):
            date = a[1] if len(a) > 1 else None
            # T日 20260818
            if date == "20260818":
                return [{"c": "00000{}".format(i)} for i in range(8)]
            # T-1 20260817
            if date == "20260817":
                return [{"c": "00000{}".format(i)} for i in range(10)]
            return []
        monkeypatch.setattr(m, "em_zt_topic_pool", fake_pool)

        # 036 mock _emotion 返 max_boards=4（绿灯因素）
        monkeypatch.setattr(
            m, "_emotion",
            lambda d: {"max_boards": 4, "ladder": [{"boards": 3, "count": 2}]},
        )

        # 038 mock NotificationService（绿灯不打扰，但仍构造一个 fake）
        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return True

            def send(self, *a, **kw) -> bool:
                return True

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        result = m.run_market_env_check("20260818")

        # 结构完整
        assert set(result.keys()) >= {
            "date", "hs300_pct", "zt_compare", "max_boards_data",
            "judge", "notified",
        }
        assert result["date"] == "20260818"
        # 034
        assert result["hs300_pct"] == 0.8
        # 035
        zc = result["zt_compare"]
        assert zc["zt_count_t1"] == 10
        assert zc["zt_count_t"] == 8
        assert zc["ratio"] == 0.8
        # 036
        mb = result["max_boards_data"]
        assert mb["max_boards"] == 4
        assert mb["is_t1_fallback"] is False
        # 037 绿灯（三因素全绿）
        assert result["judge"]["light"] == "green"
        assert result["judge"]["factors"]["hs300"] == "green"
        assert result["judge"]["factors"]["zt_count"] == "green"
        assert result["judge"]["factors"]["max_boards"] == "green"
        # 038 绿灯不打扰
        assert result["notified"] is False

    def test_end_to_end_red_light_notified(self, monkeypatch):
        """端到端红灯场景：三因素全红 → 红灯 + notified=True。"""
        from strategies import first_board_market_env as m

        # 034 沪深300 -1.5%（红）
        monkeypatch.setattr(
            m, "index_quote",
            lambda: [{"name": "沪深300", "change_pct": -1.5}],
        )

        # 035 T日涨停 2 家 / T-1 10 家 → ratio=0.2（红）
        def fake_pool(*a, **kw):
            date = a[1] if len(a) > 1 else None
            if date == "20260818":
                return [{"c": "00000{}".format(i)} for i in range(2)]
            if date == "20260817":
                return [{"c": "00000{}".format(i)} for i in range(10)]
            return []
        monkeypatch.setattr(m, "em_zt_topic_pool", fake_pool)

        # 036 max_boards=2（红）
        monkeypatch.setattr(
            m, "_emotion",
            lambda d: {"max_boards": 2, "ladder": [{"boards": 1, "count": 5}]},
        )

        # 038 mock NotificationService 可用
        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return True

            def send(self, content, route_type=None, severity=None, **kw) -> bool:
                return True

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        result = m.run_market_env_check("20260818")

        assert result["judge"]["light"] == "red"
        assert result["notified"] is True

    def test_end_to_end_all_missing_returns_yellow(self, monkeypatch):
        """端到端全部数据缺失 → 黄灯 + notified=True（黄灯也推送）。"""
        from strategies import first_board_market_env as m

        # 034 index_quote 返空
        monkeypatch.setattr(m, "index_quote", lambda: [])
        # 035 em_zt_topic_pool 返空
        monkeypatch.setattr(m, "em_zt_topic_pool", lambda *a, **kw: [])
        # 036 _emotion 返空
        monkeypatch.setattr(m, "_emotion", lambda d: {})

        # 038 NotificationService 可用
        class FakeNS:
            def __init__(self, *a, **kw):
                pass

            def is_available(self) -> bool:
                return True

            def send(self, content, route_type=None, severity=None, **kw) -> bool:
                return True

        monkeypatch.setattr(
            "notification.notification_service.NotificationService", FakeNS
        )

        result = m.run_market_env_check("20260818")

        # 全缺失 → 黄灯（中性，不误判红灯）
        assert result["judge"]["light"] == "yellow"
        # 黄灯推送
        assert result["notified"] is True
        # 各因素都是 yellow（数据缺失降级）
        assert result["judge"]["factors"]["hs300"] == "yellow"
        assert result["judge"]["factors"]["zt_count"] == "yellow"
        assert result["judge"]["factors"]["max_boards"] == "yellow"
