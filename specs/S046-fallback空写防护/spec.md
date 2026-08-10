# Spec: S046 — fallback 空写防护（限流返空不覆盖好缓存）

> 状态：已实现（2026-08-10）——R1-R4 完成：`_is_empty` + save_cache 空数据不写 / load_cache 损坏快照自愈删除 / get_with_fallback 空 fetch 降级好缓存。附带清理 275 个已污染空快照（gitignored，无仓库影响）+ git show 恢复 contract 直读的 capital_flow_605162 / dragon_tiger_605162。验证：14 新测试 + `pytest -m "not live"` 916 过。
> 级别：**small/medium**（纯后端单文件 `backend/fallback.py` + 测试；不碰外部端点，仅硬化既有缓存降级逻辑）
> 关联：`backend/fallback.py`（save_cache/load_cache/get_with_fallback）、`backend/risk_models.py:481`（capital_flow 调用方）、`../../backend/data/fallback/*.json`（运行时快照）
> 背景：2026-08-10 东财限流下 `capital_flow_605162.json` 被空写覆盖致 `tests/contract/test_models.py::TestFundFlowBaseline` 2 测试挂（已 git show 恢复快照，根因待修——本 spec）。

## 1. 问题 / 目标
`fallback.get_with_fallback` 在 fetch 返空（`[]`/`{}`，东财限流典型表现）时：
1. `save_cache` 把空 data 写进快照文件，**覆盖既有好缓存**；
2. `get_with_fallback` 把空当合法数据 `return`，调用方拿到空而非降级到缓存。
结果：一次限流污染快照，后续所有调用在 TTL 内持续读到空。

**目标**：空数据视为"取数失败"，不覆盖好缓存；fetch 空时降级返回上次好缓存（无缓存再回 fallback_value）；已损坏的空快照自愈删除。

## 2. 需求清单
- [x] R1 `_is_empty(data)`：None / 空容器（`[]`、`{}`、`""`、`()`、`set()`）为空；标量 `0`/`False` 不算空（合法值）。
- [x] R2 `save_cache`：空数据**不写文件、不覆盖内存缓存**（保护既有好数据）。
- [x] R3 `load_cache`：读到 `data` 为空的损坏快照 → 返回 None（视为未命中）并**删除该文件**自愈；清对应内存项。
- [x] R4 `get_with_fallback`：fetch 返空 → 不 save，降级到 `load_cache`；缓存命中返回好数据，否则 `fallback_value`。fetch 抛异常行为不变（降级缓存）。

## 3. 受影响文件
| 文件 | 改动 |
|---|---|
| `backend/fallback.py` | 加 `_is_empty`；save_cache/load_cache/get_with_fallback 空数据防护 |
| `backend/tests/test_fallback_empty_write.py`（新） | R1-R4 行为单测 |

## 4. 验收标准
- [x] A1 save_cache(空 list/dict/None) 后既有好缓存内容不变（文件 + 内存）
- [x] A2 load_cache 读损坏空快照返 None 且文件被删
- [x] A3 get_with_fallback fetch 返空 + 有好缓存 → 返回缓存好数据；无缓存 → 返回 fallback_value
- [x] A4 标量 0/False 不被当空（正常缓存）
- [x] A5 `pytest backend/tests/test_fallback_empty_write.py` 全过；`pytest -m "not live"`（deselect newsradar 联网测试）不回归
- [x] A6 合规：纯缓存正确性修复，无臆造（空即不写）、无私有数据外泄、无新外部端点

## 5. 合规与工程底线自查
- 空数据不臆造为缓存值，保护"判断可复现"（好快照不被空覆盖）✓
- 不碰私有数据、不新增东财端点、不走裸 requests ✓
- 仅缓存层正确性修复，无方向性输出 ✓
