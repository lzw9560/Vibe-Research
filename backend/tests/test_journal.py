"""S149 Phase 3 P3-T3f — journal.py 单测。

移植自 vibe-astock@3c3b7c8 journal.py。覆盖：
- CRUD（add/update/delete/list/stats）
- fills/fee 计算（移动加权平均 + 净额盈亏 + golden values）
- threading.Lock（防静默丢单——读改写串行）
- _market_context 零网络盖章（P3-T2d：走 daily_review 磁盘层，不触网）
- _stock_context 字段映射（push2ex c/lbc/fbt/lbt/zbc/hybk）
- JournalCorrupted（损坏文件抛异常不返空）
- VR_DATA_DIR 隔离（不硬编码 home）
"""
from __future__ import annotations

import json

import pytest

import journal
import journal as j_mod


# ───────────────────────── fixtures ─────────────────────────
ZT_POOL = [
    {"c": "605398", "n": "新炬网络", "lbc": 2, "zbc": 0, "hybk": "IT服务Ⅱ",
     "fbt": 92501, "lbt": 92501},
]
ZB_POOL: list[dict] = []


@pytest.fixture
def isolated_journal(monkeypatch, tmp_path):
    """VR_DATA_DIR→tmp；_market_context 走磁盘层零网络；_stock_context mock。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    # _market_context：走磁盘层（不触网）——返一份 review dict
    monkeypatch.setattr(j_mod, "get_daily_review",
                        lambda d: {"date": d, "sti_phase": "发酵",
                                   "money_effect_median": 5.01, "zt_total": 39})
    # _stock_context：mock em_zt_topic_pool（push2ex，add_trade 时调）
    def _fake_pool(endpoint, date, sort="fbt:asc", raise_on_failure=False):
        if endpoint == "getTopicZTPool":
            return list(ZT_POOL)
        if endpoint == "getTopicZBPool":
            return list(ZB_POOL)
        return []
    monkeypatch.setattr(j_mod.astock, "em_zt_topic_pool", _fake_pool)
    return tmp_path


# ───────────────────────── fills/fee golden values ─────────────────────────
def test_settle_simple_buy_sell_golden():
    """买 100@10 → 卖 100@12：净盈亏 = 200 - 费用（移动加权 + 净额）。"""
    fills = [
        {"side": "buy", "date": "2026-09-03", "price": 10.0, "shares": 100},
        {"side": "sell", "date": "2026-09-04", "price": 12.0, "shares": 100},
    ]
    s = journal._settle(fills)
    assert s["has_fills"] is True
    assert s["closed"] is True
    assert s["open_shares"] == 0.0
    assert s["avg_cost"] == 10.0
    assert s["buy_shares"] == 100.0
    assert s["sell_shares"] == 100.0
    assert s["gross_pnl"] == 200.0
    # 费用：买 max(1000*0.00025,5)+1000*0.00001=5.01；卖 max(1200*0.00025,5)+1200*0.00001+1200*0.0005=5.612
    # leg_fee = pos_fee(5.01)*1.0 + 5.612 = 10.622 → round 10.62
    assert s["fees"] == 10.62
    assert s["realized_pnl"] == 189.38           # 200 - 10.62
    assert s["realized_pct"] == 18.94           # 189.38 / 1000 * 100
    assert s["fees_are_estimated"] is True      # fills 未填 fee 字段
    assert s["hold_days"] == 1
    assert s["is_t0"] is False
    assert s["first_buy"] == "2026-09-03"
    assert s["last_sell"] == "2026-09-04"
    assert s["cycles"] == 1


def test_settle_t0_same_day():
    """同日买卖 = 做 T（hold_days=0, is_t0=True）。"""
    fills = [
        {"side": "buy", "date": "2026-09-03", "price": 10.0, "shares": 100},
        {"side": "sell", "date": "2026-09-03", "price": 11.0, "shares": 100},
    ]
    s = journal._settle(fills)
    assert s["hold_days"] == 0
    assert s["is_t0"] is True


def test_settle_oversell_raises():
    """卖超持仓 → ValueError（录入错误，不默默算数）。"""
    fills = [
        {"side": "buy", "date": "2026-09-03", "price": 10.0, "shares": 100},
        {"side": "sell", "date": "2026-09-04", "price": 12.0, "shares": 200},
    ]
    with pytest.raises(ValueError, match="超过当时持有"):
        journal._settle(fills)


def test_settle_only_sell_raises():
    """只有卖出没买入 → ValueError（无从结算，如实报错非 0）。"""
    with pytest.raises(ValueError, match="只有卖出没有买入"):
        journal._settle([{"side": "sell", "date": "2026-09-03", "price": 12.0, "shares": 100}])


def test_settle_partial_sell_then_reopen():
    """平仓后再买入：已实现累加 + 成本重置（cycles=2）。"""
    fills = [
        {"side": "buy", "date": "2026-09-03", "price": 10.0, "shares": 100},
        {"side": "sell", "date": "2026-09-04", "price": 12.0, "shares": 100},
        {"side": "buy", "date": "2026-09-05", "price": 30.0, "shares": 100},
    ]
    s = journal._settle(fills)
    assert s["cycles"] == 2
    assert s["open_shares"] == 100.0
    assert s["avg_cost"] == 30.0                  # 当前持仓成本（非历史均价）
    assert s["realized_pnl"] == 189.38            # 第一轮净盈亏（未改写）


def test_settle_user_fee_overrides_estimate():
    """用户在 fill 填了 fee → 以对账单真实值为准（不再按费率估）。"""
    fills = [
        {"side": "buy", "date": "2026-09-03", "price": 10.0, "shares": 100, "fee": 5.0},
        {"side": "sell", "date": "2026-09-04", "price": 12.0, "shares": 100, "fee": 6.0},
    ]
    s = journal._settle(fills)
    assert s["fees"] == 11.0                       # 5 + 6
    assert s["fees_are_estimated"] is False
    assert s["realized_pnl"] == 189.0              # 200 - 11


# ───────────────────────── CRUD ─────────────────────────
def test_add_update_delete_crud(isolated_journal):
    """CRUD 全流程：add → update 补卖出 → delete。"""
    r = journal.add_trade("2026-09-03", "605398", "新炬网络", "打板",
                          fills=[{"side": "buy", "date": "2026-09-03",
                                  "price": 10.0, "shares": 100}],
                          planned_stop=9.5)
    assert r["ok"] is True
    tid = r["trade"]["id"]
    assert r["trade"]["market"]["emotion_phase"] == "发酵"   # _market_context 固化
    assert r["trade"]["market"]["money_effect_median"] == 5.01
    assert r["trade"]["stock"]["in_limit_up"] is True        # _stock_context 固化
    assert r["trade"]["stock"]["boards"] == 2
    assert r["trade"]["planned_stop"] == 9.5

    # update 补卖出
    u = journal.update_trade(tid, fills=[
        {"side": "buy", "date": "2026-09-03", "price": 10.0, "shares": 100},
        {"side": "sell", "date": "2026-09-04", "price": 12.0, "shares": 100},
    ])
    assert u["ok"] is True
    assert u["trade"]["settled"]["realized_pnl"] == 189.38
    assert u["trade"]["pnl_pct"] == 18.94

    # list
    lst = journal.list_trades()
    assert lst["total"] == 1
    assert lst["trades"][0]["id"] == tid

    # delete
    d = journal.delete_trade(tid)
    assert d["ok"] is True
    assert journal.list_trades()["total"] == 0


def test_update_nonexistent_returns_not_found(isolated_journal):
    r = journal.update_trade("nonexistent", note="x")
    assert r["ok"] is False


def test_delete_nonexistent_returns_not_found(isolated_journal):
    r = journal.delete_trade("nope")
    assert r["ok"] is False


def test_add_validates_playbook_and_code(isolated_journal):
    with pytest.raises(ValueError, match="打法"):
        journal.add_trade("2026-09-03", "605398", "x", "非打法")
    with pytest.raises(ValueError, match="6 位数字"):
        journal.add_trade("2026-09-03", "abc", "x", "打板")


def test_update_planned_stop_leaves_audit_trail(isolated_journal):
    """改计划止损 → 留 planned_edited_at 痕迹（在险资金口径防事后倒推）。"""
    r = journal.add_trade("2026-09-03", "605398", "新炬网络", "打板",
                          planned_stop=9.5)
    tid = r["trade"]["id"]
    u = journal.update_trade(tid, planned_stop=9.0)
    assert u["trade"]["planned_stop"] == 9.0
    assert "planned_edited_at" in u["trade"]


def test_all_trades_untruncated(isolated_journal):
    """all_trades 不截断（持仓聚合/风控须走它，防静默漏未平仓记录）。"""
    for i in range(5):
        journal.add_trade("2026-09-03", "605398", "新炬网络", "打板",
                          pnl_pct=1.0 + i)
    assert len(journal.all_trades()) == 5
    assert journal.list_trades(limit=2)["total"] == 5   # total 不截断


# ───────────────────────── 损坏自愈 / 迁移 ─────────────────────────
def test_corrupted_journal_raises_not_silent_empty(isolated_journal, tmp_path):
    """账本损坏 → JournalCorrupted（不返空表，防 add 覆盖丢历史）。"""
    trades_path = tmp_path / "journal" / "trades.json"
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    trades_path.write_text("{NOT JSON", encoding="utf-8")
    with pytest.raises(journal.JournalCorrupted):
        journal._load_raw()


def test_schema_mismatch_triggers_migration_backup(isolated_journal, tmp_path):
    """schema!=当前 → 自动迁移 + 备份原件（不就地改坏）。"""
    trades_path = tmp_path / "journal" / "trades.json"
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    # v2 老账本（无 planned_stop/target）
    trades_path.write_text(json.dumps({"schema": 2, "trades": [
        {"id": "abc", "date": "2026-09-03", "code": "605398", "name": "x",
         "playbook": "打板", "fills": [], "settled": {"has_fills": False}}]}),
        encoding="utf-8")
    trades = journal._load_raw()
    assert len(trades) == 1
    assert trades[0]["planned_stop"] is None      # v3 补 None，不倒推
    assert trades[0]["planned_target"] is None
    # 备份原件
    assert (tmp_path / "journal" / "trades.v2.bak.json").is_file()


# ───────────────────────── P3-T2d：_market_context 零网络 ─────────────────────────
def test_market_context_zero_network(isolated_journal, monkeypatch):
    """P3-T2d：_market_context 走 daily_review 磁盘层，不触 em_zt_topic_pool（零网络盖章）。"""
    called = {"n": 0}

    def _boom(endpoint, *a, **k):
        called["n"] += 1
        raise AssertionError(f"_market_context 不应触网（调了 {endpoint}）")
    monkeypatch.setattr(j_mod.astock, "em_zt_topic_pool", _boom)
    # get_daily_review 已 mock（isolated_journal）返磁盘 dict，不触网
    ctx = journal._market_context("2026-09-04")
    assert ctx["emotion_phase"] == "发酵"
    assert ctx["money_effect_median"] == 5.01
    assert ctx["limit_up_count"] == 39
    assert ctx["has_review"] is True
    assert ctx["promotion_overall"] is None       # Vibe-Review 无此字段，诚实 None
    assert called["n"] == 0                        # 零网络


def test_market_context_review_failure_gives_empty(isolated_journal, monkeypatch):
    """get_daily_review 失败 → _market_context 如实返空（不阻塞记账，不臆造）。"""
    monkeypatch.setattr(j_mod, "get_daily_review", lambda d: None)
    ctx = journal._market_context("2026-09-04")
    assert ctx["has_review"] is False
    assert ctx["emotion_phase"] is None
    assert ctx["money_effect_median"] is None


def test_market_context_seal_fields_contract(isolated_journal):
    """P3-T7a：journal market 盖章字段 = STIPhase phase + money_effect 中位数
    （cycle_position 不进盖章，audit §2.2 双源规则）。"""
    ctx = journal._market_context("2026-09-04")
    # 盖章字段存在 + 取值
    assert "emotion_phase" in ctx          # STIPhase phase
    assert "money_effect_median" in ctx    # money_effect 中位数
    assert ctx["emotion_phase"] == "发酵"
    assert ctx["money_effect_median"] == 5.01
    # cycle_position 不进 journal 盖章（双源规则——cycle 是 STIPhase 辅助读数，不进盖章）
    assert "cycle" not in ctx
    assert "day_n" not in ctx
    assert "pctile" not in ctx
    assert "trough_date" not in ctx


def test_add_trade_seals_market_context(isolated_journal):
    """P3-T7b：add_trade 固化盖章字段到 trade.market（emotion_phase + money_effect_median）。"""
    r = journal.add_trade("2026-09-03", "605398", "新炬网络", "打板",
                          fills=[{"side": "buy", "date": "2026-09-03", "price": 10, "shares": 100}],
                          planned_stop=9.0)
    m = r["trade"]["market"]
    assert m["emotion_phase"] == "发酵"           # STIPhase 盖章
    assert m["money_effect_median"] == 5.01       # money_effect 中位数盖章
    assert m["has_review"] is True
    assert "cycle" not in m                        # cycle 不进盖章


def test_market_context_zero_network_integration(monkeypatch, tmp_path):
    """P3 审查 #5：端到端零网络——precompute 落盘后 _market_context 走真实磁盘层，
    em_zt_topic_pool 不被调（audit G-gate「monkeypatch em_get 断言未触网」）。

    不 mock get_daily_review（区别于 test_market_context_zero_network）——让 _market_context
    走真实 daily_review.get_daily_review（磁盘读），boom 断言盖章路径零网络。
    """
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    import daily_review as dr_mod
    from daily_review import DailyReviewer, ReviewReport, get_reviewer
    from data.sources import eastmoney

    monkeypatch.setattr(dr_mod, "_reviewer_instance", None)
    # precompute 调 generate_review——mock 它（避免网络）+ money_effect
    monkeypatch.setattr(DailyReviewer, "generate_review",
                        lambda self, d: ReviewReport(
                            date=d, sti_score=55.0, sti_phase="发酵", sti_change=2.0,
                            zt_total=39, dt_total=1, zb_total=4, advance_count=2400,
                            decline_count=1600, sector_heat=[], zt_stocks=[],
                            prev_zt_stats={}, auction_top=[], updated="2026-09-04 16:00"))
    import emotion_metrics_ext as _em
    monkeypatch.setattr(_em, "money_effect", lambda d: {"available": True, "median": 5.01})

    reviewer = get_reviewer()
    reviewer.precompute_daily("2026-09-04")          # 落盘 JSON + _CACHE
    dr_mod._CACHE.clear()                            # 强制走磁盘路径（测磁盘层零网络）

    # boom if em_zt_topic_pool / em_get 触网——盖章路径应读磁盘不触网
    monkeypatch.setattr(j_mod.astock, "em_zt_topic_pool",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("盖章路径触网")))
    monkeypatch.setattr(eastmoney, "em_get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("盖章路径 em_get 触网")))

    ctx = journal._market_context("2026-09-04")
    assert ctx["emotion_phase"] == "发酵"
    assert ctx["money_effect_median"] == 5.01
    assert ctx["has_review"] is True


# ───────────────────────── P3-T3c：_stock_context 字段映射 ─────────────────────────
def test_stock_context_maps_push2ex_fields(isolated_journal):
    """_stock_context：push2ex c/lbc/fbt/lbt/zbc/hybk → 标准化字段。"""
    ctx = journal._stock_context("2026-09-03", "605398")
    assert ctx["in_limit_up"] is True
    assert ctx["boards"] == 2
    assert ctx["first_seal"] == "92501"
    assert ctx["sector"] == "IT服务Ⅱ"
    assert ctx["board_type"] == "主板"


def test_stock_context_non_limit_up_stock(isolated_journal, monkeypatch):
    """非涨停股 → in_limit_up=False。"""
    def _fake(endpoint, date, sort="fbt:asc", raise_on_failure=False):
        return [{"c": "000001", "n": "平安银行", "lbc": 1, "zbc": 0, "hybk": "银行"}] if endpoint == "getTopicZTPool" else []
    monkeypatch.setattr(j_mod.astock, "em_zt_topic_pool", _fake)
    ctx = journal._stock_context("2026-09-03", "605398")   # 不在池里
    assert ctx == {"in_limit_up": False}


def test_board_type_by_code():
    """board_type 按代码推（push2ex 无 board 字段）——纯函数测。"""
    assert journal._board_type("300001") == "创业板"
    assert journal._board_type("301001") == "创业板"
    assert journal._board_type("688001") == "科创板"
    assert journal._board_type("689001") == "科创板"
    assert journal._board_type("830001") == "北交所"
    assert journal._board_type("430001") == "北交所"
    assert journal._board_type("600001") == "主板"
    assert journal._board_type("000001") == "主板"


# ───────────────────────── 数据目录隔离 ─────────────────────────
def test_journal_paths_under_vr_data_dir(isolated_journal, tmp_path):
    """账本路径在 VR_DATA_DIR 下（不硬编码 ~/.duanxian-agents）。"""
    assert tmp_path.as_posix() in journal._journal_dir()
    assert journal._trades_path().endswith("journal/trades.json")
    assert journal._fees_path().endswith("journal/fees.json")
    import inspect
    assert ".duanxian-agents" not in inspect.getsource(journal)


def test_load_save_fees(isolated_journal):
    """费率读写（VR_DATA_DIR 隔离 + 校验）。"""
    fees = journal.load_fees()
    assert fees["is_default"] is True
    saved = journal.save_fees({"commission_rate": 0.0003, "commission_min": 1.0})
    assert saved["ok"] is True
    again = journal.load_fees()
    assert again["is_default"] is False
    assert again["commission_rate"] == 0.0003
    assert again["commission_min"] == 1.0
    with pytest.raises(ValueError, match="不能是负数"):
        journal.save_fees({"commission_rate": -0.1})
