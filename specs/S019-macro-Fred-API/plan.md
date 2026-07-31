# Plan: S019 — 宏观特征 Fred API 接入（收尾验证）

> 状态：实现已完成，本 plan 为收尾验证 + spec 勾选闭合
> 作者：Claude  日期：2026-07-31
> 关联：`spec.md`、`../S018-多源特征工程/`、`../S017-A股涨跌预测模型栈/`

---

## 1. 现状盘点（实现已落地，spec 勾选滞后）

S019 spec 标"草案"，但代码侧 R1–R7 全部已实现并合入 develop（commit d39a48d/56bc825）。

| 需求 | spec 勾选 | 实际代码 | 落点 |
|---|---|---|---|
| R1 注册 2 FeatureSpec（us_10y_yield/dxy, source=fred_api, s2, ok） | `[ ]` | ✅ | `predict/features/macro.py:21-40` MACRO_SPECS |
| R2 `get_fred_api_key` 读 VR_DATA_DIR，缺失返 None，不日志 | `[ ]` | ✅ | `macro.py:63-76` |
| R3 `fetch_fred_series` 独立 requests 通道（非 em_get），可选代理，失败返 None | `[ ]` | ✅ | `macro.py:126-161`（VR_HTTP_PROXY 回退） |
| R4 `parse_fred_observations` 纯函数，"."→None | `[ ]` | ✅ | `macro.py:82-120` |
| R5 不入 HEAD_FEATURE_SUBSETS → 后已加入 short_sector | `[x]` | ✅ | `predict/feature_interface.py:43-44` `*(s.name for s in MACRO_SPECS)` |
| R6 Fred 走独立通道，不裸 em_get；key 隔离 VR_DATA_DIR | `[ ]` | ✅ | fetch_fred_series 用 `requests` 非 em_get；key 经 `resolve_data_dir()` |
| R7 可复现：series_id 固定、解析纯函数、key 不参与计算 | `[ ]` | ✅ | FRED_SERIES 常量 + parse 纯函数 |

**佐证**：
- 远程 fred_api_key 在位（`/home/vdb/turing/code/Vibe-Research/.vibe-research/fred_api_key`，32 字节）。
- `t16_real_train.py` 的 FRED macro 通道（DGS10 + DTWEXBGS）已在 2026-07-30 远程 live 冒烟跑通（单指数 T16 真实冒烟用到 `build_macro_map` → `fetch_fred`）。
- `tests/test_features_macro.py` 存在（49 处 test/parse_fred/get_fred_api_key/fetch_fred/MACRO_SPECS 匹配）。
- 全量 814 passed（远程 not live）含 test_features_macro。

## 2. 剩余工作（仅验证 + 收尾）

S019 无新代码要写。剩余 3 件验证收尾事：

1. **离线单测确认绿**：远程 `pytest -m "not live" tests/test_features_macro.py`。
2. **live 冒烟确认**：远程跑 `fetch_fred_series("DGS10", key)` + `("DTWEXBGS", key)` 返非空、`parse_fred_observations` 出非空 list（key 已在位）。可借 `t16_real_train.py` 现有 FRED 调用旁路验证，或加一条 `@pytest.mark.live` 标记的冒烟测试入 `test_features_macro.py`。
3. **spec 勾选闭合**：把 spec.md R1–R4/R6–R7 与 A1–A4/A6 的 `[ ]` 改 `[x]`，状态行"草案"改"已实现"，记录 commit + 验证日期。

## 3. 风险

- 🟢 无实现风险（代码已落地并跑通）。唯一风险是 spec 勾选滞后导致误判未完成——本 plan 闭合之。
- 🟡 Fred 限流/代理不稳：fetch_fred_series 已降级返 None，调用方 fallback，零影响。

## 4. 退出条件

- A1–A4/A6 全绿勾选；live 冒烟有记录；spec 状态行改"已实现 2026-07-31"。
