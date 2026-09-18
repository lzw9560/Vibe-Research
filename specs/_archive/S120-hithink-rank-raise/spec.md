# Spec: S120 — hithink 三榜源不可达 raise（AI 出口诚实化）

> 状态：已实现(2026-08-31)
> 作者：lzw9560  日期：2026-08-31
> 关联：S118 scan #1 `ai-hithink-rank-empty-on-failure`（HIGH confirmed_lying, worth_fixing）/ S104（hithink_src 直连）

## 1. 问题 / 目标

S118 scan 判 `ai-hithink-rank-empty-on-failure` confirmed_lying：hithink 飙升榜/热股榜/异动榜（`skyrocket`/`hot_stock`/`anomaly_list`, hithink_src.py:242-269）在源不可达（熔断/Key 缺/4xx5xx/重试耗尽/net err）时 `_http_get` 返 None，三函数 `if data is None: return []` 把"源断"与"合法空榜（code==0, item=[]）"坍缩成同一 `[]`。`_http_get` 返 None vs `{"item":[]}` 本可区分，但 `return []` 蓄意坍缩。`[]` 经 stock_tools.query_* → chat.py:232 `json.dumps` 成 `"[]"` 喂 LLM，`registry.execute` 仅异常才返 `{"error"}`，`[]` 不抛故原样透传零标注。LLM 把"源不可达"当"今日无榜"下方向研判（触 §1.2 不臆造底线）。

⚠ 关联 hithink APIKey 泄漏待轮换——轮换后旧 key 401（非 `_RETRYABLE_HTTP_STATUS` → record_failure → None → `[]`）将活体触发此撒谎路径，须在轮换前修掉。

目标：源断 raise（非返 `[]`），让 `registry.execute` 兜成 `{"error"}` 喂 LLM（诚实），router 同步 502；合法空榜仍 `[]`（不误伤盘后空）。

## 2. 背景

- `_http_get`（hithink_src.py:115-175）返 None on 失败 / data dict on 成功（code==0），`{"item":[]}` 是合法空。返 None 路径：熔断 allow_request False / Key 缺 DependencyMissing / HTTP 4xx5xx 非重试 / 重试耗尽 / net err。
- 同仓诚实范式：`query_global_stock`（stock_tools.py:78）/ `worldmonitor_query`（worldmonitor_tools.py:55）失败返 `{"error":"暂不可达"}`，唯 hithink 三榜偏离——正是 S118 scan 用作支撑的对比。
- `registry.execute`（registry.py:200-201）仅异常返 `{"error"}`；router market.py:63-92 三端点已 `try/except`（待 impl 验）→ 502。
- `test_s104_hithink_source.py:218-220` `test_skyrocket_failure_empty` 断言 `skyrocket()==[]`（固化撒谎）——须改。

## 3. 需求清单

- [ ] R1 `skyrocket`/`hot_stock`/`anomaly_list`（hithink_src.py:242/253/261）`if data is None: return []` → `if data is None: raise RuntimeError("hithink <飙升榜/热股榜/异动榜> 暂不可达（熔断/离线/API Key 缺失）")`。合法空（`_items({"item":[]})`→`[]`）路径保留不抛。
- [ ] R2 改 `test_s104` `test_skyrocket_failure_empty` → `test_skyrocket_failure_raises`：`_http_get` 返 None 时 `pytest.raises(RuntimeError)`。加 `test_skyrocket_legit_empty_returns_empty`：`_http_get` 返 `{"item":[]}` → skyrocket 返 `[]` 不抛（合法路径保留）。hot_stock/anomaly_list 同款测试。
- [ ] R3 验 router market.py:63-92 三端点 `try/except` 兜 raise → 502（非 200+`{"data":[]}`）。若已兜零改动，否则加。
- [ ] R4 全量 `pytest -m "not live" --deselect` newsradar/s032/spec_consistency 0 回归。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/data/sources/hithink_src.py` | skyrocket/hot_stock/anomaly_list `return []`→raise RuntimeError |
| `backend/tests/test_s104_hithink_source.py` | `test_skyrocket_failure_empty`→`_raises`；加合法空测试 |
| `backend/routers/market.py` | （读验）确认三端点 try/except→502 |

## 5. 设计方案

raise `RuntimeError`（非 typed 异常）——`registry.execute` 与 router 均捕 `Exception`，typed 无额外收益；re-raise 保 `_http_get` 原始失败上下文（已在 logger.warning 落盘）。合法空（code==0, item=[]）路径 `_items(data)`→`[]` 不抛，与源断 raise 区分（正是 S118 crack 诉求）。

备选返 `{"error":...}` dict——破 `list[dict]` 返回签名，且 LLM 仍可能当合法 dict 解读，否决。备选 typed `SourceUnavailable`——与 `registry.execute`/router 宽捕语义无差，多一层类无收益，否决。

## 6. 验收标准

- [ ] A1 源断（`_http_get` None）→ skyrocket/hot_stock/anomaly_list raise → `registry.execute` `{"error"}` 喂 LLM（非 `"[]"`）
- [ ] A2 合法空（`_http_get` `{"item":[]}`）→ 返 `[]` 不抛（盘后空诚实保留）
- [ ] A3 router 端点源断 → 502（非 200+`{"data":[]}`）
- [ ] A4 全量 pytest 0 回归

## 7. 合规与工程底线自查

- [x] 研判/推荐：源断标 error 喂 LLM（不臆造"无榜"），系统能力；无新方向建议
- [x] 判断可复现：纯代码逻辑，测试钉死；不涉财务验算
- [x] 涨停四池/连板：不涉
- [x] 私有数据：不涉（hithink key 经 `_resolve_api_key` 读 env，不进代码）
- [x] em_get 防封：不涉（hithink 非 em_get 路径，自有 `breaker('hithink')`）

## 8. 测试计划

`pytest -m "not live"` + 改 1 测 + 加合法空测（三榜）。`--deselect` 既有 flaky（newsradar/s032/spec_consistency）。

## 9. 风险与回滚

- **风险**：router 未兜 raise → 500。缓解：R3 验，缺则加 try。
- **回滚**：三函数改回 `return []`（一行）。
