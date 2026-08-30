# Spec: S119 — eastmoney_datacenter 源断信号传播（恢复 S112 fetch_ok 前提）

> 状态：已实现(2026-08-31)
> 作者：lzw9560  日期：2026-08-31
> 关联：S111（登记册）/ S112（risk-trio fetch_ok fix，本 spec 修其被源端绕过的前提）/ S118（scan #15 `source-em-swallow-defeats-fetch-ok`，fix_now confirmed_lying）

## 1. 问题 / 目标

S118 scan 判 `source-em-swallow-defeats-fetch-ok` 为 **fix_now confirmed_lying**：`eastmoney_datacenter`（eastmoney.py:366-379）`except Exception: return []` 吞所有异常，`dragon_tiger_board` 三次调它无 try/except → 源断（限流/IP 封/ut 缺/JSON 错）时不抛异常 → `get_with_fallback_meta`（fallback.py:191-195）`fetch_ok=True`（"fetch 返回无 exception"）→ risk_models.py:305 `return 0.0, "ok"` —— **源断被伪装成"近期未上龙虎榜 ok"**，risk 静默归零。

S112 的 fetch_ok 逻辑没错，但**前提（源断会抛异常）被源端吞异常破坏**，是活回归。目标：让源断信号能传到 `get_with_fallback_meta`，恢复 S112 的 ok/missing 区分。

## 2. 背景

- S112 post-fix：`get_with_fallback_meta` 加 `fetch_ok` 标志，risk-trio empty 分支按 `fetch_ok` 区分 ok(未上榜) vs missing(源断)。`fetch_ok=True` iff `fetch_fn()` 不抛异常（fallback.py:191-195 + docstring :184-185）。
- 链环四点抽验坐实：①eastmoney_datacenter `except Exception: return []`（eastmoney.py:372-373）②dragon_tiger_board 三调无 try/except（eastmoney.py:641/657/661）③get_with_fallback_meta `meta["fetch_ok"]=True` 在 `data=fetch_fn()` 无异常时（fallback.py:194-195）④risk_models.py:305 `return 0.0, "ok" if meta.get("fetch_ok") else "missing"`。
- eastmoney_datacenter 是共享函数，10+ 调用方（dragon_tiger_board×3 / margin_trading / block_trade / lockup_expiry / gstock×3 / seat_engine.service / fund_flow predict×3 / tools×2）。改全局契约（一律 raise）blast radius 大且多数消费者诚实性未扫（critic missed_dim #6：em_get 消费者吞异常→返空结构全量未扫）。
- 已抽验 risk-trio 三处（risk_models.py:305 / ~374 / ~528）均读 `meta.fetch_ok` → 已在 `get_with_fallback_meta` 后。

## 3. 需求清单

- [ ] R1 `eastmoney_datacenter` 加 `raise_on_failure: bool = False` 参数（默认 False = 既有 `[]` 行为，向后兼容）；异常路径 `if raise_on_failure: raise`（re-raise 原异常，保 em_get 原始错误信息），否则 `return []`（不变）；HTTP 成功但 `result.data` 空（真无数据）仍 `return []`（合法空保留，不抛）。**保护 margin_trading/block_trade/lockup_expiry/gstock/fund_flow predict 等 10+ 直调消费者零影响。**
- [ ] R2 `dragon_tiger_board` 加 `raise_on_failure: bool = False` 参数，透传其 3 次 `eastmoney_datacenter` 内调（DETAILSNEW :641 / BUY :657 / SELL :661）；risk-trio 两 lambda（risk_models.py:284 `_get_dragon_tiger_risk` + :508 `_calculate_concentration_risk`）传 `raise_on_failure=True`。其余 dragon_tiger_board 调用方（fund_flow/routers/first_board_filter）用默认 False 不变（YAGNI——这些路径未 confirmed_lying）。
- [ ] R2b `_pull_records`（seat_engine/service.py:62）加 `raise_on_failure: bool = False` 透传 `eastmoney_datacenter`；`compute_consensus_signal` 3 调（:234/:242/:247，seat-info 腿）传 `raise_on_failure=True`。`build_seat_profiles`(:156/:162) + `precompute_daily`(:411/:416) 用默认 False 不变。
- [ ] R3 ✅ 已审（读验）：dragon_tiger_board 5 调用方全 try/except 兜——fund_flow.py:46（try→"龙虎榜未取得"）/ stock_financial.py:97（try+_cached）/ stock_data.py:229（_safe_call）/ first_board_filter.py:706+995（try）/ topology.py:225（_collect_shared_sets try→空集 continue）。_pull_records 的 risk-trio 路径经 get_with_fallback_meta（risk_models.py:354 _get_seat_info）。非 risk-trio _pull_records 调用方（build_seat_profiles/precompute_daily）用默认 False 不变。
- [ ] R4 测试钉死：①源断（monkeypatch em_get 抛）+ risk-trio 路径 → `get_with_fallback_meta` fetch_ok=False → risk "missing" 非 "ok"；②真无榜（datacenter 返 `[]` 无异常）+ risk-trio → fetch_ok=True → "ok"（合法路径保留）；③`raise_on_failure=False`（默认）→ 既有 `[]` 行为，dragon_tiger_board 其他调用方 + margin_trading 等零影响。
- [ ] R5 全量 `pytest -m "not live" --deselect` newsradar/s032 flaky 0 回归。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/eastmoney.py` | `eastmoney_datacenter` 加 `raise_on_failure` 参数 + 异常分支；`dragon_tiger_board` 加 `raise_on_failure` 透传 3 内调 |
| `backend/risk_models.py` | `:284` + `:508` 两 lambda 加 `raise_on_failure=True`（risk-trio dragon_tiger 两腿 opt-in） |
| `backend/seat_engine/service.py` | `_pull_records` 加 `raise_on_failure` 透传；`compute_consensus_signal` 3 调加 `raise_on_failure=True`（seat-info 腿 opt-in） |
| `backend/tests/test_data_honesty.py` | 加 R4 三测试钉死诚实行为 |

## 5. 设计方案

**选 opt-in 参数（`raise_on_failure` 默认 False）而非全局改契约**。取舍：

- **全局改（finder 原案"eastmoney_datacenter 一律 raise"）**：单点覆盖所有消费者，但 10+ 调用方（margin_trading/block_trade/lockup_expiry/gstock/fund_flow）诚实性未扫（critic missed_dim #6），改契约可能引入未审回归 + 破坏既有 `[]` mock 测试（test_data_honesty.py:598 / test_fund_flow_* 多处 monkeypatch 返 `[]`）。YAGNI 否决：只修 confirmed_lying 的 dragon_tiger 路径，其余留下一轮 scan 判。
- **opt-in 参数**：零 blast radius（默认 False 不影响其他消费者），仅 dragon_tiger_board opt-in 真。re-raise 原异常（非 typed SourceUnavailable）保 em_get 原始错误信息，`get_with_fallback_meta` debug 日志已捕 `e`。
- 备选 `eastmoney_datacenter_strict` 新函数：同效但 DRY 分叉，否决。
- 备选返 `(rows, ok)` 元组：破签名，blast radius 同全局改，否决。

## 6. 验收标准

- [ ] A1 源断 + `raise_on_failure=True` → risk "missing"（非 "ok"），risk=0.0 仍（风险评分不变，仅状态诚实）
- [ ] A2 真无榜 + `raise_on_failure=True` → risk "ok"（合法路径不变）
- [ ] A3 `raise_on_failure=False`（默认）→ 既有 `[]` 行为，margin_trading/block_trade/lockup_expiry/gstock/fund_flow 零影响
- [ ] A4 全量 pytest 0 回归

## 7. 合规与工程底线自查

- [x] 研判/推荐：本修复让 risk_status 诚实标 missing 而非 ok（不撒谎），系统能力；无新方向建议，无需新风险提醒
- [x] 判断可复现：纯代码逻辑，测试钉死；不涉财务数值验算（无需 financial_rigor/report_audit）
- [x] 涨停四池/连板：不涉
- [x] 私有数据：不涉
- [x] em_get 防封：eastmoney_datacenter 已走 em_get（本 spec 不改 em_get 路径，仅改异常传播）

## 8. 测试计划

`pytest -m "not live"` + 3 新测试（R4）。`--deselect` newsradar global intel + s032 refresh_loop flaky（既有 pre-existing，非本 spec）。

## 9. 风险与回滚

- **风险**：`dragon_tiger_board` 有非 risk-trio 直调方未审 → raise 裸抛 500。缓解：R3 审全调用方，直调方加 try 或确认路由兜底。
- **回滚**：`raise_on_failure` 默认 False，dragon_tiger_board 改回不传参即恢复旧行为（参数加性，无破坏性）。
