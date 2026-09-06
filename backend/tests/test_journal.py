# -*- coding: utf-8 -*-
"""S166 fresh tests — journal CRUD + _settle 时序结算 + corruption 防覆盖 + fees。

离线：_market_context / _stock_context 的网络边界被 monkeypatch 截断（get_daily_review /
em_zt_topic_pool 打桩），一次请求不发。_settle 是纯函数，直接喂成交明细算。
"""
from __future__ import annotations

import json
import os

import pytest

import journal


# ---- fixtures ----
@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """每个用例独立 VR_DATA_DIR + 零网络盖章/票况。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    # _market_context 读 get_daily_review → 打桩（零网络）
    monkeypatch.setattr(journal, "get_daily_review", lambda d: {
        "sti_phase": "高潮", "money_effect_median": 1.2, "zt_total": 33,
    })
    # _stock_context 读 astock.em_zt_topic_pool → 打桩（零网络）
    import astock
    monkeypatch.setattr(astock, "em_zt_topic_pool", lambda *a, **k: [])
    return journal


_ZERO_FEES = {"commission_rate": 0.0, "commission_min": 0.0,
              "stamp_tax_rate": 0.0, "transfer_fee_rate": 0.0}


# ============================ _settle 时序结算 ============================
class TestSettle:
    def test_no_fills(self, fresh):
        assert fresh._settle([]) == {"has_fills": False, "closed": False}

    def test_only_sells_raises(self, fresh):
        with pytest.raises(ValueError, match="只有卖出没有买入"):
            fresh._settle([{"side": "sell", "date": "2026-08-01",
                            "price": 12.0, "shares": 100}], _ZERO_FEES)

    def test_simple_buy_sell_same_day(self, fresh):
        s = fresh._settle([
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
            {"side": "sell", "date": "2026-08-01", "price": 12.0, "shares": 100},
        ], _ZERO_FEES)
        assert s["closed"] is True
        assert s["open_shares"] == 0
        assert s["avg_cost"] == 10.0
        assert s["realized_pnl"] == 200.0
        assert s["realized_pct"] == 20.0
        assert s["hold_days"] == 0 and s["is_t0"] is True
        assert s["cycles"] == 1

    def test_moving_weighted_avg_partial_sell(self, fresh):
        # 买 100@10 + 100@20 → 均价 15；卖 100@18 → 已实现 300，剩余 100 均价仍 15
        s = fresh._settle([
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
            {"side": "buy", "date": "2026-08-01", "price": 20.0, "shares": 100},
            {"side": "sell", "date": "2026-08-02", "price": 18.0, "shares": 100},
        ], _ZERO_FEES)
        assert s["closed"] is False
        assert s["open_shares"] == 100
        assert s["avg_cost"] == 15.0          # 剩余均价不变
        assert s["realized_pnl"] == 300.0
        assert s["amount"] == 3000.0          # 峰值占用 = 100*10 + 100*20

    def test_reentry_after_close_new_cycle(self, fresh):
        # 10 买 100 → 20 全卖 → 30 再买 100：已实现 +1000，当前成本 30，cycles=2
        s = fresh._settle([
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
            {"side": "sell", "date": "2026-08-02", "price": 20.0, "shares": 100},
            {"side": "buy", "date": "2026-08-03", "price": 30.0, "shares": 100},
        ], _ZERO_FEES)
        assert s["closed"] is False
        assert s["cycles"] == 2
        assert s["realized_pnl"] == 1000.0
        assert s["avg_cost"] == 30.0          # 新周期成本，不被旧盈亏改写
        assert s["open_shares"] == 100

    def test_oversell_raises(self, fresh):
        with pytest.raises(ValueError, match="超过当时持有"):
            fresh._settle([
                {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
                {"side": "sell", "date": "2026-08-02", "price": 12.0, "shares": 200},
            ], _ZERO_FEES)

    def test_fees_deducted_from_net(self, fresh):
        # 卖出收印花税 + 佣金；realized_pnl 是净额
        cfg = {"commission_rate": 0.00025, "commission_min": 5.0,
               "stamp_tax_rate": 0.0005, "transfer_fee_rate": 0.00001}
        s = fresh._settle([
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 1000},
            {"side": "sell", "date": "2026-08-02", "price": 12.0, "shares": 1000},
        ], cfg)
        # 毛额 (12-10)*1000 = 2000；费用 = 买佣金 max(10000*0.00025,5)=5 + 卖佣金5 + 印花 12000*0.0005=6 + 过户(买0.1+卖0.12)
        assert s["gross_pnl"] == 2000.0
        assert s["fees"] > 0
        assert s["realized_pnl"] < 2000.0      # 净额扣了费
        assert s["fees_are_estimated"] is True

    def test_realized_by_date_splits_sells(self, fresh):
        # 两天分别减仓 → realized_by_date 各记一天
        s = fresh._settle([
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 200},
            {"side": "sell", "date": "2026-08-02", "price": 12.0, "shares": 100},
            {"side": "sell", "date": "2026-08-03", "price": 11.0, "shares": 100},
        ], _ZERO_FEES)
        assert set(s["realized_by_date"].keys()) == {"2026-08-02", "2026-08-03"}

    def test_explicit_fill_fee_used(self, fresh):
        # 填了 fee 就以它为准，不再按费率估
        s = fresh._settle([
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100, "fee": 3.0},
            {"side": "sell", "date": "2026-08-02", "price": 12.0, "shares": 100, "fee": 4.0},
        ], _ZERO_FEES)
        assert s["fees"] == 7.0
        assert s["fees_are_estimated"] is False

    def test_stop_above_cost_zero_at_risk_basis(self, fresh):
        # 锁定盈利时 avg_cost 仍按持仓算（at_risk 测负在险=0）
        s = fresh._settle([
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
        ], _ZERO_FEES)
        assert s["avg_cost"] == 10.0 and s["open_shares"] == 100


# ============================ CRUD ============================
class TestCRUD:
    def test_add_then_list(self, fresh):
        # 零费率：让 realized_pct 精确可断言（默认费率下小单佣金最低收取 5 元/边会吃掉一截）
        fresh.save_fees({"commission_rate": 0.0, "commission_min": 0.0,
                         "stamp_tax_rate": 0.0, "transfer_fee_rate": 0.0})
        r = fresh.add_trade("2026-08-01", "600519", "贵州茅台", "打板",
                            fills=[{"side": "buy", "date": "2026-08-01",
                                    "price": 10.0, "shares": 100},
                                   {"side": "sell", "date": "2026-08-01",
                                    "price": 12.0, "shares": 100}])
        assert r["ok"] and r["trade"]["code"] == "600519"
        lst = fresh.list_trades()
        assert lst["total"] == 1
        assert lst["trades"][0]["settled"]["realized_pct"] == 20.0

    def test_add_pct_only_no_fills(self, fresh):
        r = fresh.add_trade("2026-08-01", "000001", "平安", "低吸", pnl_pct=5.5)
        assert r["trade"]["pnl_pct"] == 5.5
        assert r["trade"]["settled"]["has_fills"] is False

    def test_add_rejects_bad_code(self, fresh):
        with pytest.raises(ValueError, match="6 位数字"):
            fresh.add_trade("2026-08-01", "abc", "x", "打板")  # 非数字

    def test_add_rejects_bad_playbook(self, fresh):
        with pytest.raises(ValueError, match="打法"):
            fresh.add_trade("2026-08-01", "600519", "x", "瞎炒")

    def test_add_rejects_future_date(self, fresh):
        with pytest.raises(ValueError, match="未来日期"):
            fresh.add_trade("2099-01-01", "600519", "x", "打板")

    def test_update_adds_sell_and_resettles(self, fresh):
        fresh.save_fees({"commission_rate": 0.0, "commission_min": 0.0,
                         "stamp_tax_rate": 0.0, "transfer_fee_rate": 0.0})
        r = fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                            fills=[{"side": "buy", "date": "2026-08-01",
                                    "price": 10.0, "shares": 100}],
                            planned_stop=9.0)
        tid = r["trade"]["id"]
        assert r["trade"]["planned_stop"] == 9.0
        # 补卖出
        up = fresh.update_trade(tid, fills=[
            {"side": "buy", "date": "2026-08-01", "price": 10.0, "shares": 100},
            {"side": "sell", "date": "2026-08-02", "price": 12.0, "shares": 100}])
        assert up["ok"]
        assert up["trade"]["settled"]["closed"] is True
        assert up["trade"]["settled"]["realized_pct"] == 20.0

    def test_update_planned_stop_leaves_audit_trail(self, fresh):
        r = fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                            fills=[{"side": "buy", "date": "2026-08-01",
                                    "price": 10.0, "shares": 100}],
                            planned_stop=9.0)
        tid = r["trade"]["id"]
        up = fresh.update_trade(tid, planned_stop=8.0)
        assert up["trade"]["planned_stop"] == 8.0
        assert "planned_edited_at" in up["trade"]   # 留痕

    def test_delete(self, fresh):
        r = fresh.add_trade("2026-08-01", "600519", "茅台", "打板", pnl_pct=3.0)
        tid = r["trade"]["id"]
        assert fresh.delete_trade(tid)["ok"] is True
        assert fresh.list_trades()["total"] == 0
        assert fresh.delete_trade("nonexistent")["ok"] is False

    def test_all_trades_untruncated(self, fresh):
        for i in range(5):
            fresh.add_trade("2026-08-01", "600519", "茅台", "打板", pnl_pct=float(i))
        assert len(fresh.all_trades()) == 5
        assert len(fresh.list_trades(limit=2)["trades"]) == 2  # 截断 vs 全量

    def test_stats_groups(self, fresh):
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板", pnl_pct=5.0, as_planned=True)
        fresh.add_trade("2026-08-01", "000001", "平安", "低吸", pnl_pct=-3.0, as_planned=False)
        st = fresh.stats()
        assert st["available"] is True
        assert st["overall"]["count"] == 2
        assert "打板" in st["by_playbook"] and "低吸" in st["by_playbook"]
        assert "按计划" in st["by_planned"] and "计划外" in st["by_planned"]


# ============================ corruption 防覆盖 ============================
class TestCorruption:
    def test_corrupt_file_raises_not_silent_overwrite(self, fresh, tmp_path):
        # 先建账本再加一笔（确保目录存在）
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板", pnl_pct=3.0)
        path = fresh._trades_path()
        # 写坏它
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        # 再 add 必须抛 JournalCorrupted，绝不能当空账本覆盖
        with pytest.raises(fresh.JournalCorrupted):
            fresh.add_trade("2026-08-02", "000001", "平安", "低吸", pnl_pct=2.0)

    def test_bad_schema_structure_raises(self, fresh):
        fresh.add_trade("2026-08-01", "600519", "茅台", "打板", pnl_pct=3.0)
        path = fresh._trades_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"no_trades_key": []}, fh)
        with pytest.raises(fresh.JournalCorrupted):
            fresh.list_trades()


# ============================ fees ============================
class TestFees:
    def test_load_default(self, fresh):
        cfg = fresh.load_fees()
        assert cfg["is_default"] is True
        assert cfg["commission_rate"] == fresh.DEFAULT_FEES["commission_rate"]

    def test_save_then_load(self, fresh):
        r = fresh.save_fees({"commission_rate": 0.001, "commission_min": 1.0,
                              "stamp_tax_rate": 0.001, "transfer_fee_rate": 0.00002})
        assert r["ok"] is True
        cfg = fresh.load_fees()
        assert cfg["is_default"] is False
        assert cfg["commission_rate"] == 0.001

    def test_save_rejects_negative(self, fresh):
        with pytest.raises(ValueError, match="不能是负数"):
            fresh.save_fees({"commission_rate": -0.1})

    def test_save_rejects_absurd_rate(self, fresh):
        with pytest.raises(ValueError, match="不像费率"):
            fresh.save_fees({"commission_rate": 0.5})


# ============================ 市场盖章 ============================
class TestStamp:
    def test_market_context_stamped_from_review(self, fresh):
        r = fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                            fills=[{"side": "buy", "date": "2026-08-01",
                                    "price": 10.0, "shares": 100}])
        m = r["trade"]["market"]
        assert m["emotion_phase"] == "高潮"
        assert m["money_effect_median"] == 1.2
        assert m["limit_up_count"] == 33
        assert m["has_review"] is True

    def test_stock_context_no_limit_up_when_pool_empty(self, fresh):
        r = fresh.add_trade("2026-08-01", "600519", "茅台", "打板",
                            fills=[{"side": "buy", "date": "2026-08-01",
                                    "price": 10.0, "shares": 100}])
        assert r["trade"]["stock"]["in_limit_up"] is False
