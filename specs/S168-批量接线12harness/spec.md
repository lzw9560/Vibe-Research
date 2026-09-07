# Spec: S168 — 12 个 RAW harness 批量接线 §44v2 verifier

> 状态：草案 | 日期：2026-09-07 | 分级：medium（helper + 12 脚本接线 + 测试）issue 层单轮 review | 关联：S161/S163/S160/S165/multiline-strategy-direction

## 0. 问题/目标

底座 S161-S167 建好 §44v2 验证框架，但 12 个已有 lift harness 全 RAW——自己算 lift/排列/走步，不调 verify()，不落 Recorder，不记 lineage。只有 s44_gap_run_60d.py 一条接了。12 个候选 edge 的 lift 数字散 .scratch/ JSON，无正式 verdict（5 值 enum），无可复现记录，无血缘。

目标：建共享接线 helper，12 harness 各调它，出 12 个 §44v2 verdict，落 Recorder + lineage。platform_breakout 旗舰，其余 11 并行。

fresh 心态：基建是测谎仪不是打板机——先测 12 个已有假设看哪些活/死，再在活的上面建 capture，不预设成功不恋战。

## 1. 背景

- 底座已建：S161 verify()（verifier.py:165 design-agnostic edge_type 显式）/ Recorder.save()（recorder.py:125 SQLite append-only）/ S163 lineage.record()（lineage.py:158 write-once）
- 唯一 WIRED 范例：s44_gap_run_60d.py（event_verdict line 193 → verify edge_type="event" + Recorder.save + pit_store + lineage）
- 12 个 RAW harness 在 backend/tools/*_lift.py，各自 frozen_commit + by_day 数据（survivors_by_day + raw_by_day universe）+ 自己的 day_paired_lift + permutation null + walk-forward
- 全用本地 four_state（4 值）非 S161 Verdict（5 值 enum + edge_type + tradeable + dsr/pbo/haircut/min_trl）
- _verdict_to_dict 工具函数只在 s44_gap_run_60d.py:207，未共享
- platform_breakout_lift.py：lift 1.079/n946/130 天/3 arm × 2 regime，冻结 74295b9，DEFAULT_PATH_PARAMS=(-3,+8,3)
- 实测：12 脚本全 RAW（grep verify( 零命中），全有 by_day 数据结构

## 2. 需求清单

- [ ] R1 共享接线 helper `backend/tools/_s44_wire.py`：wire_verdict() = verify() → _verdict_to_dict → Recorder.save() → lineage.record()，返 Verdict。从 s44_gap_run_60d.py:207 提取 _verdict_to_dict 去重
- [ ] R2 platform_breakout 接线（旗舰）：从 run_platform_breakout_lift() 的 tight/confirm/both_by_day（survivors）+ raw_by_day（universe）提取 return series + dates + survivors_by_day + universe_by_day，调 wire_verdict(edge_type="selection")，出 3 arm × 2 regime = 6 verdict
- [ ] R3 其余 11 harness 批量接线：每个 main() 末尾加 wire_verdict() 调用，edge_type 按测试性质选（见 §4 表）
- [ ] R4 每个 verdict 落 Recorder（data_snapshot_id + input_hashes + return_series + dates + params + frozen_commit + verdict dict）
- [ ] R5 每个 verdict 记 lineage（artifact_id="verifier:{line_id}"，script=脚本路径，inputs=参数，output=verdict dict）
- [ ] R6 verdict 输出人类可读摘要（status 5 值 + edge_type + lift + n + days_robust + note），与 s44_gap_run_60d.py 输出格式对齐
- [ ] R7 data_snapshot_id = frozen_commit[:8] + line_id + sha256(return_series)[:12]（不依赖 pit_store——12 harness 数据已由 frozen_commit 锁定；pit_store 留给需 pin live 数据的新线路）
- [ ] R8 诚实标注：n<200 或 days_robust<60 verdict 标 underpowered 不外推（verify() R6 gate 内建，接线方不 override）
- [ ] R9 s44_gap_run_60d.py 的 _verdict_to_dict 改从 _s44_wire import（去重不复制）

## 3. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/_s44_wire.py` | 新建：wire_verdict() + _verdict_to_dict()（从 s44_gap_run_60d.py 提取）|
| `backend/tools/platform_breakout_lift.py` | +30 行：run() 末尾调 wire_verdict × 6（3 arm × 2 regime）|
| `backend/tools/s44_gap_run_60d.py` | -5 行：_verdict_to_dict 改 import 自 _s44_wire |
| `backend/tools/block_trade_lift.py` | +20 行：调 wire_verdict selection |
| `backend/tools/first_board_layer_lift.py` | +20 行 |
| `backend/tools/first_plate_h2_lift.py` | +20 行（已 falsify 0.7843 接线确认）|
| `backend/tools/gap_window_lift.py` | +20 行（can score select bigger gaps）|
| `backend/tools/index_ma20_regime_lift.py` | +20 行 |
| `backend/tools/lianban_lift.py` | +20 行 |
| `backend/tools/lockup_lift.py` | +20 行（unlock_by_day vs raw_by_day）|
| `backend/tools/low_absorption_c3_lift.py` | +20 行 |
| `backend/tools/miaoban_superset_31d_lift.py` | +20 行 |
| `backend/tools/valuation_pe_lift.py` | +20 行 |
| `backend/tools/zt_pool_seal_time_lift.py` | +20 行 |

## 4. 设计方案

### 共享 helper 签名

```
wire_verdict(
    *, line_id, returns, dates, edge_type, frozen_commit,
    survivors_by_day=None, universe_by_day=None,  # selection 时必传
    n_comparisons=1, round_trip_cost=0.0,
    script="", params=None,
) -> Verdict
```

内部流程：verify() → _verdict_to_dict → Recorder.save → lineage.record → print 摘要 → 返 Verdict

### 12 个 harness 的 edge_type 映射

全部是 **selection**（测的是"某过滤能否选到比 raw 更好的股"，全用 day_paired_lift + survivors vs universe）：

| harness | survivors | universe | 备注 |
|---|---|---|---|
| platform_breakout | tight/confirm/both_by_day | raw_by_day | 旗舰 lift 1.079 |
| first_board_layer | layer 分组 | raw | 首板分层 |
| first_plate_h2 | seal_time 分组 | raw | 已 falsify 0.7843 |
| gap_window | top(score) | all | 已 falsify 0.942x |
| index_ma20_regime | bull subset | all | regime 过滤 |
| lianban | 连板数分组 | raw | 连板选股 |
| lockup | unlock_by_day | raw_by_day | 解禁 underperform |
| low_absorption_c3 | c3 filtered | raw | 低吸 |
| miaoban_superset_31d | miaoban | raw | 秒板 |
| valuation_pe | 低PE/高PE | all | 已 falsify <2x |
| zt_pool_seal_time | seal_time 分组 | raw | 封板时间 |
| block_trade | block_trade | universe | 大宗折价 |

注意：gap 的 event verdict（隔夜 gap 群体收益 >0）已由 s44_gap_run_60d.py（WIRED）跑完 robust_edge thin。gap_window_lift.py 跑的是 selection verdict（score 能否选更大 gap），已 falsify 0.942x。接线只是让它出正式 5 值 enum verdict 落 Recorder，不是重跑。

### 为什么不选其他方案

- **只接 platform_breakout 一条**：接线模式相同，做一条不如批量 12 条。architecture 视角明确推荐批量。
- **从零建新 breakout 线**：platform_breakout_lift.py 已有完整统计，从零建是重复劳动。先接线出 verdict，robust 才建 capture。
- **加 pit_store 集成**：YAGNI。12 harness 数据已由 frozen_commit + 脚本内缓存锁定，不需要 pit_store 再 pin。pit_store 留给需要 pin live 数据的新线路（如竞价量比等盘中线）。

## 5. 验收标准

- [ ] A1 _s44_wire.py 的 wire_verdict() 单元测试：mock verify + Recorder + lineage，断言调用参数正确（AAA 模式）
- [ ] A2 platform_breakout 接线后跑 `python backend/tools/platform_breakout_lift.py`，输出 Verdict（5 值 enum + edge_type + selection_lift + n + days_robust + note），Recorder 有记录，lineage 有记录
- [ ] A3 12 个 harness 全部接线后各跑一遍，Recorder 有 12 条记录（line_id 唯一），lineage 有 12 条
- [ ] A4 Recorder 的 return_series 可重算出相同 verdict（verdict-reproducibility 判据：读 return_series → 重调 verify → status 一致）
- [ ] A5 `pytest -m "not live" --deselect 3 flaky` 全绿（新增测试 + 预存无回归）
- [ ] A6 platform_breakout verdict 诚实标注：n<200 或 days_robust<60 标 underpowered 不外推（verify() R6 gate 内建，接线方不 override）

## 6. 合规与工程底线自查

- [x] 不臆造：verify() 纯函数（same inputs → same Verdict），Recorder 落 return_series 可重算，lineage 记 input/output hash——不臆造不心算
- [x] 私有数据隔离：Recorder DB 在 .vibe-research/，已 .gitignore
- [x] em_get 防封：12 harness 用已有数据源，不新增 em_get 调用
- [x] §44 降级参考性建议：verdict 是统计判定非买卖建议

## 7. 测试计划

- 单元：_s44_wire.py wire_verdict() mock 测试（AAA：Arrange mock verify/Recorder/lineage → Act 调 wire_verdict → Assert 参数正确 + Verdict 返回）
- 集成：platform_breakout_lift.py 端到端跑，检查 Recorder + lineage 有记录 + verdict 5 值 enum
- 离线快测：`pytest -m "not live"` + 3 个 flaky deselect（s032/newsradar/s040）
- 手动：跑 platform_breakout_lift.py，看输出 verdict 是否 5 值 enum + 诚实标注 + Recorder 落盘

## 8. 风险与回滚

- **风险**：部分 harness 的 return series 可能 n 不够（<200 或 days<60），verify() 标 underpowered 不出 robust。这不是 bug 是诚实标注（§44v2 R6 gate），正是 north-star"诚实"要求的。
- **风险**：selection edge_type 需 survivors_by_day + universe_by_day，部分 harness 数据结构格式可能略有差异（如 defaultdict vs dict），需逐个适配。
- **回滚**：每个 harness 接线是独立 commit，可逐个 revert。_s44_wire.py 是新文件，删除即回滚。s44_gap_run_60d.py 的改动只是 import 路径，改回本地 _verdict_to_dict 即可。

## 9. 依赖与 deferred 子项

- **无阻塞依赖**：底座 S161-S167 全建完，12 harness 全有数据，NOW 可做。
- **deferred — pit_store 集成**：当前用 frozen_commit + hash 做 data_snapshot_id。新线路（竞价量比/封单/秒板等盘中线）需要 pin live 数据时再加 pit_store，YAGNI。
- **deferred — capture 建设**：platform_breakout 接线后看 verdict。robust 才建 capture（信号接入打板工作流 + 实时执行）；falsified 就弃，pivot 到均值回归（均值回归的 lift 脚本也在 12 个里，同步接线出 verdict）。不恋战。
- **deferred — 盘中线**：竞价量比/封单 trajectory/异动排名等盘中 edge 等 S167 攒 30-60 天数据，不在本 spec 范围。
- **deferred — 长线价值/成长/分红**：数据 NOW 但验证周期长（1-3 年 return series），反馈慢，排中期。
