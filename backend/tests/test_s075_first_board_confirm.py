# -*- coding: utf-8 -*-
"""S075 Phase 2 候选确认单测（tasks.md 039-040）。

覆盖：
- 039 竞价过滤（高开>5%/低开/1-3%健康/3-5%偏大观察/数据缺失降级）
- 040 开盘确认（5分钟不破/跌破/量比不足/数据缺失/空samples/端到端结构/5维度落盘）

mock 模式：monkeypatch.setattr("strategies.first_board_confirm.tencent_quote", mock)
- tencent_quote(codes: list[str]) -> dict[str, dict]
- 字段：open/price/last_close/vol_ratio/amount_wan（无 last，spec 写的 last 实际是 price）
"""

import pytest


# ── 公共 mock 数据工厂 ───────────────────────────────────────────────────

def _make_tencent_quote(
    code: str = "000001", open_price=10.0, last_close=9.8,
    price=10.1, vol_ratio=1.8, amount_wan=5000.0,
) -> dict:
    """构造 tencent_quote 单股返回结构（dict[code, dict]）。"""
    return {
        code: {
            "name": "测试股", "price": price, "last_close": last_close,
            "open": open_price, "vol_ratio": vol_ratio,
            "amount_wan": amount_wan, "turnover_pct": 5.0, "change_pct": 2.0,
        }
    }


def _make_auction_data(code: str = "000001", pct: float = 2.0,
                       open_price=10.0, last_close=9.8, amount_wan=5000.0) -> dict:
    """构造 fetch_auction_data 产出格式。"""
    return {
        code: {
            "auction_open": open_price, "last_close": last_close,
            "auction_open_pct": pct, "auction_amount_wan": amount_wan,
        }
    }


# =========================================================================
# 039 竞价过滤
# =========================================================================

class TestFilterByAuction:
    """039：测试竞价过滤。"""

    def test_high_open_above_5pct_dropped(self):
        """高开>5% 放弃（追高风险）。"""
        from strategies.first_board_confirm import filter_by_auction
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = _make_auction_data("000001", pct=6.0, open_price=10.6, last_close=10.0)
        confirmed, dropped = filter_by_auction(cands, auction)
        assert len(confirmed) == 0
        assert len(dropped) == 1
        assert dropped[0]["code"] == "000001"
        assert "追高" in dropped[0]["reason"]
        assert "6.0" in dropped[0]["reason"]

    def test_low_open_dropped(self):
        """低开（≤0）放弃（核按钮风险）。"""
        from strategies.first_board_confirm import filter_by_auction
        # pct=-1.0 低开
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = _make_auction_data("000001", pct=-1.0, open_price=9.9, last_close=10.0)
        confirmed, dropped = filter_by_auction(cands, auction)
        assert len(confirmed) == 0
        assert len(dropped) == 1
        assert "核按钮" in dropped[0]["reason"]

    def test_low_open_zero_pct_dropped(self):
        """pct=0.0（平开）也剔除（≤0 规则）。"""
        from strategies.first_board_confirm import filter_by_auction
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = _make_auction_data("000001", pct=0.0, open_price=10.0, last_close=10.0)
        confirmed, dropped = filter_by_auction(cands, auction)
        assert len(confirmed) == 0
        assert len(dropped) == 1
        assert "核按钮" in dropped[0]["reason"]

    def test_high_open_1_to_3pct_confirmed(self):
        """高开 1-3% 健康区间，保留。"""
        from strategies.first_board_confirm import filter_by_auction
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = _make_auction_data("000001", pct=2.0, open_price=10.2, last_close=10.0)
        confirmed, dropped = filter_by_auction(cands, auction)
        assert len(confirmed) == 1
        assert len(dropped) == 0
        assert confirmed[0]["code"] == "000001"
        # auction 字段附加到候选
        assert "auction" in confirmed[0]
        assert confirmed[0]["auction"]["auction_open_pct"] == 2.0
        # 1-3% 健康区间无 note
        assert "note" not in confirmed[0]["auction"] or confirmed[0]["auction"].get("note") is None

    def test_high_open_3_to_5pct_kept_with_flag(self):
        """高开 3-5% 保留但标"高开偏大观察"（不剔除，落盘标注）。"""
        from strategies.first_board_confirm import filter_by_auction
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = _make_auction_data("000001", pct=4.0, open_price=10.4, last_close=10.0)
        confirmed, dropped = filter_by_auction(cands, auction)
        assert len(confirmed) == 1  # 保留不剔除
        assert len(dropped) == 0
        # 落盘标注"偏大观察"
        assert "note" in confirmed[0]["auction"]
        assert "偏大观察" in confirmed[0]["auction"]["note"]
        assert "4.0" in confirmed[0]["auction"]["note"]

    def test_data_missing_degraded_kept(self):
        """竞价数据缺失时不剔除（降级保留，标"竞价数据缺失"）。"""
        from strategies.first_board_confirm import filter_by_auction
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = {}  # 空数据
        confirmed, dropped = filter_by_auction(cands, auction)
        assert len(confirmed) == 1  # 降级保留
        assert len(dropped) == 0
        assert confirmed[0]["auction"]["note"] == "竞价数据缺失"

    def test_mixed_candidates(self):
        """混合：1 只高开>5%剔除 + 1 只健康保留 + 1 只数据缺失保留。"""
        from strategies.first_board_confirm import filter_by_auction
        cands = [
            {"code": "000001", "name": "A", "total": 60.0},
            {"code": "000002", "name": "B", "total": 65.0},
            {"code": "000003", "name": "C", "total": 55.0},
        ]
        auction = {
            "000001": _make_auction_data("000001", pct=6.0)["000001"],  # 剔除
            "000002": _make_auction_data("000002", pct=2.0)["000002"],  # 保留
            # 000003 缺失 → 降级保留
        }
        confirmed, dropped = filter_by_auction(cands, auction)
        assert len(confirmed) == 2  # 000002 + 000003
        assert len(dropped) == 1     # 000001
        codes = [c["code"] for c in confirmed]
        assert "000002" in codes and "000003" in codes
        assert dropped[0]["code"] == "000001"


# =========================================================================
# 040 开盘确认
# =========================================================================

class TestCheckOpenSupport:
    """040：测试开盘确认（check_open_support）。"""

    def test_open_held_and_vol_ratio_high_confirmed(self, monkeypatch):
        """5分钟不破开盘价 + 量比>1.5 → 确认。"""
        from strategies.first_board_confirm import check_open_support
        # mock tencent_quote 返 vol_ratio=1.8
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=1.8)
        )
        open_price = 10.0
        samples = [10.1, 10.2, 10.0, 10.1, 10.3]  # 都 >= 10.0
        r = check_open_support("000001", open_price, samples)
        assert r["open_held"] is True
        assert r["vol_ratio"] == 1.8
        assert r["vol_ratio_ok"] is True
        assert r["confirmed"] is True
        assert r["min_low"] == 10.0
        assert r["samples"] == samples

    def test_open_broken_dropped(self, monkeypatch):
        """5分钟内跌破开盘价 → 放弃（open_held=False）。"""
        from strategies.first_board_confirm import check_open_support
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=2.0)
        )
        open_price = 10.0
        samples = [10.0, 9.9, 9.8, 10.0, 10.1]  # 9.8 < 10.0 破开盘
        r = check_open_support("000001", open_price, samples)
        assert r["open_held"] is False
        assert r["confirmed"] is False  # ③ 不满足
        assert r["min_low"] == 9.8

    def test_vol_ratio_low_dropped(self, monkeypatch):
        """量比<1.5 → 缩量观望放弃（②量比不满足，confirmed=False）。"""
        from strategies.first_board_confirm import check_open_support
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=0.8)
        )
        open_price = 10.0
        samples = [10.1, 10.2, 10.0, 10.1, 10.3]  # open_held=True
        r = check_open_support("000001", open_price, samples)
        assert r["open_held"] is True
        assert r["vol_ratio"] == 0.8
        assert r["vol_ratio_ok"] is False  # 0.8 < 1.5
        assert r["confirmed"] is False     # ② 不满足

    def test_vol_ratio_missing_degraded(self, monkeypatch):
        """vol_ratio 取不到（tencent_quote 返空）→ 不崩，confirmed=False。"""
        from strategies.first_board_confirm import check_open_support
        # tencent_quote 返空 dict → vol_ratio=None
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: {}
        )
        open_price = 10.0
        samples = [10.1, 10.2, 10.0, 10.1, 10.3]
        r = check_open_support("000001", open_price, samples)
        assert r["vol_ratio"] is None
        assert r["vol_ratio_ok"] is False
        assert r["confirmed"] is False  # ② 不满足
        assert r["open_held"] is True   # ③ 满足

    def test_vol_ratio_exception_no_crash(self, monkeypatch):
        """tencent_quote 抛异常 → 不崩，vol_ratio=None，confirmed=False。"""
        from strategies.first_board_confirm import check_open_support
        def boom(codes):
            raise ConnectionError("网络故障")
        monkeypatch.setattr("strategies.first_board_confirm.tencent_quote", boom)
        open_price = 10.0
        samples = [10.1, 10.2, 10.0, 10.1, 10.3]
        r = check_open_support("000001", open_price, samples)
        assert r["vol_ratio"] is None
        assert r["confirmed"] is False
        assert r["open_held"] is True

    def test_empty_samples(self, monkeypatch):
        """空 samples → open_held=False，confirmed=False。"""
        from strategies.first_board_confirm import check_open_support
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=2.0)
        )
        open_price = 10.0
        samples = []  # 空采样
        r = check_open_support("000001", open_price, samples)
        assert r["open_held"] is False  # bool([]) and ... = False
        assert r["min_low"] is None
        assert r["confirmed"] is False


class TestConfirmCandidates:
    """040：测试 confirm_candidates（开盘价缺失/降级路径）。"""

    def test_open_price_missing(self, monkeypatch):
        """开盘价取不到（auction 无 auction_open + fetch_open_price 返 None）→ confirmed=False。"""
        from strategies.first_board_confirm import confirm_candidates
        # mock fetch_open_price 返 None（tencent_quote 返空）
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: {}
        )
        # 候选 auction 无 auction_open 字段
        cands = [{"code": "000001", "name": "A", "total": 60.0,
                  "auction": {"note": "竞价数据缺失"}}]
        samples = {"000001": [10.1, 10.2, 10.0]}
        out = confirm_candidates(cands, samples)
        assert len(out) == 1
        assert out[0]["open_price"] is None
        assert out[0]["confirmed"] is False
        assert out[0]["open_held"] is False
        assert "note" in out[0]
        assert "开盘价缺失" in out[0]["note"]

    def test_open_price_from_auction(self, monkeypatch):
        """开盘价优先用 auction.auction_open（不调 fetch_open_price）。"""
        from strategies.first_board_confirm import confirm_candidates
        # tencent_quote mock（check_open_support 会调取 vol_ratio）
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=2.0)
        )
        cands = [{"code": "000001", "name": "A", "total": 60.0,
                  "auction": {"auction_open": 10.0, "auction_open_pct": 2.0}}]
        samples = {"000001": [10.1, 10.2, 10.0, 10.1, 10.3]}
        out = confirm_candidates(cands, samples)
        assert len(out) == 1
        assert out[0]["open_price"] == 10.0  # 从 auction 取
        assert out[0]["open_held"] is True
        assert out[0]["vol_ratio"] == 2.0
        assert out[0]["confirmed"] is True

    def test_samples_missing_confirmed_false(self, monkeypatch):
        """samples 缺失（open_samples 无该 code）→ confirmed=False。"""
        from strategies.first_board_confirm import confirm_candidates
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=2.0)
        )
        cands = [{"code": "000001", "name": "A", "total": 60.0,
                  "auction": {"auction_open": 10.0, "auction_open_pct": 2.0}}]
        samples = {}  # 缺 000001 的 samples
        out = confirm_candidates(cands, samples)
        assert len(out) == 1
        assert out[0]["samples"] == []
        assert out[0]["open_held"] is False  # 空_samples → False
        assert out[0]["confirmed"] is False


# =========================================================================
# 040 端到端
# =========================================================================

class TestRunFirstBoardConfirm:
    """040：测试主入口 run_first_board_confirm 端到端。"""

    def test_end_to_end_structure(self, monkeypatch):
        """端到端：mock candidates+auction+samples，验证返回结构完整。"""
        from strategies.first_board_confirm import run_first_board_confirm
        # mock tencent_quote（check_open_support 取 vol_ratio 用）
        def mock_tq(codes):
            out = {}
            for c in codes:
                if c == "000001":
                    out[c] = _make_tencent_quote(c, vol_ratio=1.8)[c]
                elif c == "000002":
                    out[c] = _make_tencent_quote(c, vol_ratio=1.2)[c]  # 量比不足
            return out
        monkeypatch.setattr("strategies.first_board_confirm.tencent_quote", mock_tq)

        cands = [
            {"code": "000001", "name": "兴欣新材", "total": 63.4},
            {"code": "000002", "name": "金健米业", "total": 60.0},
        ]
        auction = {
            "000001": _make_auction_data("000001", pct=2.0, open_price=10.2)["000001"],
            "000002": _make_auction_data("000002", pct=2.0, open_price=10.2)["000002"],
        }
        samples = {
            "000001": [10.2, 10.3, 10.2, 10.4, 10.5],  # open_held=True
            "000002": [10.2, 10.1, 10.0, 9.9, 9.8],   # 9.8<10.2 破开盘
        }
        r = run_first_board_confirm(cands, auction, samples)

        # 结构完整
        assert set(r.keys()) == {
            "auction_confirmed", "auction_dropped",
            "open_confirmed", "open_dropped", "confirm_records",
        }
        # 竞价：两只都 2% 高开 → 都保留
        assert len(r["auction_confirmed"]) == 2
        assert len(r["auction_dropped"]) == 0
        # 开盘：000001 open_held+vol_ratio=1.8 确认；000002 破开盘剔除
        assert len(r["open_confirmed"]) == 1
        assert len(r["open_dropped"]) == 1
        assert r["open_confirmed"][0]["code"] == "000001"
        assert r["open_dropped"][0]["code"] == "000002"

    def test_confirm_records_have_5_dims(self, monkeypatch):
        """落盘记录含 5 维度字段（auction_open_pct/vol_ratio/open_held/auction_vol_ratio/manual_bid_ask_ratio）。"""
        from strategies.first_board_confirm import run_first_board_confirm
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=1.8)
        )
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = {"000001": _make_auction_data("000001", pct=2.0, open_price=10.2)["000001"]}
        samples = {"000001": [10.2, 10.3, 10.2, 10.4, 10.5]}
        r = run_first_board_confirm(cands, auction, samples)

        assert len(r["confirm_records"]) >= 1
        rec = r["confirm_records"][0]
        # 5 维度字段
        assert "auction_open_pct" in rec
        assert "vol_ratio" in rec
        assert "open_held" in rec
        assert "auction_vol_ratio" in rec
        assert "manual_bid_ask_ratio" in rec
        # 其他必要字段
        assert "code" in rec and "confirmed" in rec and "stage" in rec
        # 值校验
        assert rec["auction_open_pct"] == 2.0
        assert rec["vol_ratio"] == 1.8
        assert rec["open_held"] is True
        assert rec["auction_vol_ratio"] == 5000.0  # auction_amount_wan 近似
        assert rec["manual_bid_ask_ratio"] is None  # ⑤ 人工标注，字段预留
        assert rec["confirmed"] is True
        assert rec["stage"] == "open"

    def test_auction_dropped_in_records(self, monkeypatch):
        """竞价剔除也进 confirm_records（stage=auction）。"""
        from strategies.first_board_confirm import run_first_board_confirm
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=1.8)
        )
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = {"000001": _make_auction_data("000001", pct=6.0)["000001"]}  # 高开>5% 剔除
        samples = {"000001": [10.6, 10.7, 10.6, 10.8, 10.9]}
        r = run_first_board_confirm(cands, auction, samples)

        # 竞价剔除 → 不进开盘确认，open_confirmed/open_dropped 都空
        assert len(r["auction_dropped"]) == 1
        assert len(r["open_confirmed"]) == 0
        assert len(r["open_dropped"]) == 0
        # confirm_records 含竞价剔除记录
        assert len(r["confirm_records"]) == 1
        rec = r["confirm_records"][0]
        assert rec["stage"] == "auction"
        assert rec["confirmed"] is False
        assert rec["auction_open_pct"] == 6.0
        assert "追高" in rec.get("reason", "")

    def test_no_open_samples_skips_open_stage(self, monkeypatch):
        """open_samples=None → 跳过开盘确认，open_confirmed/open_dropped 都空。"""
        from strategies.first_board_confirm import run_first_board_confirm
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", vol_ratio=1.8)
        )
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        auction = {"000001": _make_auction_data("000001", pct=2.0)["000001"]}
        r = run_first_board_confirm(cands, auction, None)  # 无 samples

        assert len(r["auction_confirmed"]) == 1
        assert len(r["auction_dropped"]) == 0
        assert r["open_confirmed"] == []
        assert r["open_dropped"] == []
        # confirm_records 只有竞价层记录（auction_confirmed 无 confirmed 字段，不进 records）
        # 实际：auction_confirmed 不进 confirm_records（只有 dropped + open 进）
        # 所以 confirm_records 应为空
        assert r["confirm_records"] == []

    def test_fetch_auction_data_internal_called(self, monkeypatch):
        """auction_data=None → 内部调 fetch_auction_data（mock tencent_quote）。"""
        from strategies.first_board_confirm import run_first_board_confirm
        # mock tencent_quote 返 open=10.2, last_close=10.0 → pct=2.0
        monkeypatch.setattr(
            "strategies.first_board_confirm.tencent_quote",
            lambda codes: _make_tencent_quote("000001", open_price=10.2,
                                              last_close=10.0, vol_ratio=1.8)
        )
        cands = [{"code": "000001", "name": "A", "total": 60.0}]
        samples = {"000001": [10.2, 10.3, 10.2, 10.4, 10.5]}
        # auction_data=None → 内部 fetch_auction_data 取
        r = run_first_board_confirm(cands, None, samples)

        # 内部算出 pct=2.0 → 竞价保留
        assert len(r["auction_confirmed"]) == 1
        assert r["auction_confirmed"][0]["auction"]["auction_open_pct"] == 2.0
        # 开盘确认（vol_ratio=1.8, open_held=True）
        assert len(r["open_confirmed"]) == 1
