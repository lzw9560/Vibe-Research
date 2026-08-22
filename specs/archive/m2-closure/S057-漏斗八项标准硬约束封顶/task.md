# S057 原子任务清单

> 级别：medium（跨层，>50 行；无新外部数据源）
> 基线：后端 1022 passed / 前端 40 files 298 tests（S059 验收后）。
> 依赖：无外部，复用现有漏斗源（涨停池/腾讯行情/漏斗 sources）。

## S1 八项检查纯函数

- [x] T1 `candidate_funnel/eight_standards.py`（新）：
  - `check_eight_standards(ind: IndicatorSet, market_ctx: dict) -> EightStandardResult`
  - 三态判定（pass/fail/missing），DSA 八项：①流通市值 30-150 亿 ②换手 5-20% ③量比≥1.5 ④10:30 前封板 ⑤开板≤1 ⑥封单>流通市值 1% ⑦题材热度 TOP10 ⑧低位首板或平台突破
  - 各项输出 {status, actual, expected, note}
  - 纯函数单测：八项各条件边界值 + missing 三态 + 未过数计数 ✅ 29 passed

- [x] T2 `candidate_funnel/models.py` 增 `EightStandardResult` / `EightStandardItem` 类型：
  - `EightStandardItem: {key, label, status: pass|fail|missing, actual, expected, note}`
  - `EightStandardResult: {items: list, fail_count: int, missing_count: int}`
  - `DiagnosisCard` 增 `eight_standards: EightStandardResult | None = None` + `capped`/`cap_reason`（向后兼容）
  - commit 门：既有模型测试不退化 ✅

## S2 封顶逻辑接入漏斗

- [x] T3 `candidate_funnel/thresholds.py` 增封顶阈值：
  - `EIGHT_STANDARD_CAP_THRESHOLD = 55`（可配）
  - `EIGHT_STANDARD_FAIL_CAP_COUNT = 3`（未过数阈值）
  - commit 门：配置可读 ✅

- [x] T4 `candidate_funnel/diagnosis.py` 接入封顶：
  - `build_diagnosis_card` 调用 `check_eight_standards`，结果挂入 DiagnosisCard
  - 未过数≥3 → `capped=True` + `cap_reason`（封顶阈值 55 在消费侧实施）
  - `IndicatorSet` 增 `float_market_cap` 字段；activity source 塞入
  - commit 门：诊断卡单测绿 ✅

- [x] T5 `candidate_funnel/diagnosis.py` 诊断卡接入八项（与 T4 合并）：
  - `build_diagnosis_card` 内调用 `check_eight_standards` 并挂入 ✅

## S3 前端展示

- [x] T6 前端 DiagnosisCard 加八项明细区：
  - 逐项展示 通过/未过/缺失 + 实际值
  - 缺失显「—」不显示假值
  - 封顶标记「封顶 55（3 项未过）」
  - vitest：渲染 / 缺失「—」/ 封顶标记 / 无 eight_standards 不渲染 ✅ 4 passed

## S4 全测与合规

- [x] T7 离线全测：`pytest -m "not live" --no-cov` 全绿（后端 +29 新测）；`tsc + vitest run` 全绿（41 files 302 tests）
- [x] T8 合规自查：三态判定不臆造（missing 显式标记）；无新外部数据源；封顶阈值可配可回滚

## S5 归档

- [x] T9 spec.md 状态改已实现 + commit `docs(S057): 验收`
