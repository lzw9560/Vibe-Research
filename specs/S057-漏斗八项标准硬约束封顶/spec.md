# Spec: S057 — 漏斗八项标准硬约束封顶

> 状态：草案
> 作者：Codex（DSA 借鉴 grill 会话）  日期：2026-08-11
> 级别：**medium**（跨层，>50 行；无新外部数据源）
> 流程门：develop 直提 + 勤 commit；issue 级 review；简化验收
> 关联：`.scratch/dsa-board-borrowing/issues/01`（Q4 裁决）、`candidate_funnel/`（funnel/thresholds/diagnosis）、DSA `SEAL_PLATE_ARCHITECTURE.md` §5（八项标准原型）

## 1. 问题 / 目标

VR 漏斗只有过/不过，没有 DSA 式"多项未过 → 评分封顶"的纪律机制。Q4 裁决：八项标准落漏斗评分层，作独立评估维度（不参与过滤），未过≥3 项 → 最终得分封顶；基因分不动（历史统计语义与当日纪律约束分开）。

## 2. 背景

- DSA 八项标准：①流通市值 30-150 亿 ②换手 5-20% ③量比≥1.5 ④10:30 前封板 ⑤开板≤1 ⑥封单>流通市值 1% ⑦题材热度 TOP10 ⑧低位首板或平台突破；≥3 项未过 → 评分上限 55。
- DSA 实现「数据缺失→放行」会虚增通过数，**与 VR 不臆造数据红线冲突** → 本 spec 改为缺失显式标记 `missing`，不计入通过数也不计入未过数（独立第三态）。
- VR 数据可得性：①②④⑤⑥⑦可由涨停池/腾讯行情/现有漏斗源得到；③量比、⑧股价位置需 K 线（`limitup_screener.kline_rebuild` 已有基础），不可得时 missing。

## 3. 需求清单

- [ ] R1 `candidate_funnel/eight_standards.py`（新）：八项检查纯函数，输入单股快照 + 热点板块列表，输出逐项 `{pass/fail/missing}` + 未过数
- [ ] R2 封顶逻辑：未过数≥3 → 漏斗最终得分封顶（阈值默认 55，进 `thresholds.py` 可配）；封顶标记 `capped=true` + 原因进 FunnelResult
- [ ] R3 `diagnosis.py` 诊断卡：逐项展示 通过/未过/缺失 + 实际值 vs 期望区间（DSA EightStandardCheck 形态）
- [ ] R4 前端：诊断卡八项明细 + FunnelMatrix 封顶标记（如「封顶 55（3 项未过）」）
- [ ] R5 热点 TOP10 口径：复用现有板块热度数据（涨停池板块聚合），无则⑦记 missing

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/eight_standards.py`（新） | 八项检查纯函数 |
| `backend/candidate_funnel/funnel.py` | 接入封顶 |
| `backend/candidate_funnel/thresholds.py` | 封顶阈值 + 各项区间配置 |
| `backend/candidate_funnel/diagnosis.py` | 诊断卡逐项明细 |
| `frontend/.../FunnelMatrix*` / 诊断卡组件 | 封顶标记 + 八项明细 |

## 5. 设计方案

- 三态判定（pass/fail/missing）而非 DSA 的二态放行——缺失数据不参与计数，诊断卡如实展示，守住不臆造红线。
- 封顶只作用于漏斗最终得分排序展示，不改变基因分、不删除候选（与软 gate 哲学一致）。
- 备选不选：基因分上封顶（语义混淆，Q4 已否）；仅展示层标签（无纪律效力）。

## 6. 验收标准

- [ ] A1 pytest -m "not live" 全过：八项各条件边界值单测 + missing 三态 + 封顶触发/不触发
- [ ] A2 冒烟：构造 3 项未过样本，端点返回 capped=true 且得分=阈值
- [ ] A3 tsc + vitest 过；诊断卡 missing 显示「—」不显示假值

## 7. 合规与工程底线自查

- [ ] 属客观数据呈现 + 纪律标注（§1.1），无买卖指令
- [ ] 不臆造：missing 显式标记，不补默认值
- [ ] 无新外部数据源（复用现有漏斗源）
- [ ] 判断可复现：诊断卡带实际值与期望区间

## 8. 测试计划

离线：八项纯函数单测 + 漏斗集成测试 + 前端组件测试。手动：诊断卡走查。

## 9. 风险与回滚

- 封顶误伤：阈值可配 + 诊断卡可解释；回滚＝阈值置 100（等效关闭）。
