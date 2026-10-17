# Spec: S238 — 打板手艺参考·非 edge 归档声明

> 状态：已归档（声明性，2026-10-17）
> 作者：claude  日期：2026-10-17
> 关联：`docs/daban-workflow.md`、memory `tail-dip-falsified-2026-10-17`、S229（§44 v3 证伪方法）、S234（短线排雷过滤器——打板的工程化对照）、S233（打板工作流 router）、S231（打板纪律门禁，DEFERRED）

> ⚠️ **本 spec 是声明性归档，非实现性策略 spec。** 无代码改动、无路由接线、无 scheduler 接入。
> 主体是固化"打板=非 edge 手艺参考、不接生产"这个边界，防止未来漂移。

## 1. 问题 / 目标

打板选股规则已穷尽证伪（memory `limitup-factor-sweep` 19 信号全 falsified / `short-term-strategy-sweep` 22 信号 0 存活 / `edge-exhaustive-5batch` 300+ 候选 0 alpha）。但打板作为"人执行的情绪溢价手艺"仍有参考价值。需固化边界：**打板 = 非 edge、不接生产、不进策略库/不接交易信号**，定位为 `docs/daban-workflow.md` 纯手艺参考。

本 spec 不做 edge 验证（用户明确"不做 edge 验证"）。打板已证伪，本 spec 是归档声明，非策略实现。

## 2. 背景

- **09-18 拐点**：做减法、冻结新 spec/基建。打板已证伪，不开新打板策略 spec。本 S238 是声明性归档（减法），非新策略（加法）。
- **§0 SDD 分级**：纯文档/参考属 small 级免 spec。用户选择以 spec 形式正式固化打板"非 edge"定位，作为项目决策记录，故落本 spec。
- **打板 edge 在"人的手艺"**（盘感/情绪周期/封单真伪/退潮管手），不可回测、不可复制成规则——所以规则化打板选股 0 存活，不矛盾于"打板有人能赚"。
- 证伪记录：memory `limitup-factor-sweep-2026-10-06` / `short-term-strategy-sweep-2026-10-06` / `edge-exhaustive-5batch-2026-09-28` / `tail-dip-falsified-2026-10-17`（tail-dip 是低吸变体，同属打板类，已 8 年 walk-forward 证伪）。

## 3. 需求清单

- [x] R1 维护 `docs/daban-workflow.md` 作为打板手艺唯一参考（已存在，2026-10-17 落）
- [x] R2 文档顶部钉死状态：非 edge / 不接入生产 / 不进策略 spec / 不接交易信号 / 先模拟盘（已满足）
- [x] R3 本 spec 声明打板不接 `chat.TOOLS` / 不接 `scheduled_tasks` / 不接路由作为买入信号
- [ ] R4 任何未来会话想把打板当 edge 重启，须先过 §44 v3 walk-forward OOS + R12 size-matched + Bonferroni（参照 `tail-dip-falsified-2026-10-17` 流程 / `_audit_tail_dip_full.py`），否则拒绝
- [x] R5 不开新打板策略 spec（本 S238 是归档声明，不是策略实现 spec）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `docs/daban-workflow.md` | 已存在（2026-10-17 落），纯参考文档，无代码逻辑 |
| `specs/S238-daban-workflow-archive/spec.md` | 本 spec（声明性，无代码改动） |

**无代码 / 路由 / scheduler 改动。**

## 5. 设计方案

本 spec 是**声明性归档**，不是实现性策略 spec。

- **取舍**：用户要 spec 化打板。但打板已证伪 + 非 edge + 无实现环节，落成"实现性 spec"会形式错配（无受影响代码 / 无功能验收）。落成"声明性 spec"既满足 spec 化要求，又不违 09-18 冻结。
- **备选为何不选**：
  - 只留文档 + memory（不落 spec）：边际最省，但用户要 spec 形式正式记录，未选。
  - 落实现性 spec（假装打板是策略要实现）：违 09-18 冻结 + 做减法，且形式错配，不选。
- **边界声明**：打板定位 = 非 edge 手艺参考，不接生产；重启须过证伪流程（R4）。

## 6. 验收标准

- [x] A1 `docs/daban-workflow.md` 存在且顶部状态标注完整（非 edge / 不接生产 / 不进 spec / 先模拟盘）——已满足
- [x] A2 `specs/S238-daban-workflow-archive/spec.md` 存在本 spec
- [x] A3 grep 核验：本 spec 本身无代码接线（纯文档 + 声明）——已满足
- 注：本 spec 无"功能实现验收"——声明性 spec 的验收是"文档存在 + 边界声明完整 + 本 spec 无未授权接线"。

**A3 核验发现的相关但范围外项**（属各自 spec/归档处理，非 S238 范围）：
- `backend/routers/tail_dip.py` 的 `GET /api/strategy/tail-dip/scan` 仍在产暴露 tail-dip 买入候选 → 属 tail-dip 归档未完成项（见 memory `tail-dip-falsified-2026-10-17`），待单独处理（API 标证伪/下线）。
- `backend/routers/limitup_workflow.py`（S233 打板工作流 router）→ 属 S233 自身 spec。
- `backend/routers/discipline_gate.py`（S231 打板纪律门禁，已 DEFERRED，只展示 verdict 不接买入）→ 属 S231 自身 spec。

## 7. 合规与工程底线自查（逐条确认）

- [x] 本 spec 不涉及数据输出 / AI 提示词 / 交易信号——是声明性归档，不触 §1.2 工程底线（不臆造 / 私有数据隔离 / 防封均不涉及）
- [x] 不新增东财端点（无数据采集）
- [x] 用户私有数据不涉及
- [x] 本 spec 明确打板不接交易信号，反而加固工程底线（防止证伪策略污染真盘）

## 7.1 §44 v3 anti-fake-edge sanity（2026-09-24 S229）

- 本 spec **不做 edge 验证**（用户明确）。打板已证伪（`limitup-factor-sweep` 等），本 spec 是归档声明，不触发 v3 sanity（无 edge 声称）。
- R4 把 v3 sanity 作为"未来重启前置门"固化——任何想翻案者须先过 walk-forward OOS + R12 + Bonferroni，否则拒绝。这是防漂移门，不是当下验证。

## 8. 测试计划

- 无功能测试（声明性 spec，无代码改动）。
- A3 grep 核验已跑：`grep -rn "tail_dip\|打板\|strategy4\|错杀" backend/routers backend/ai backend/scheduler` —— 本 spec 无接线；发现的相关项（tail-dip API / S233 / S231）见 §6 A3 记录，范围外。

## 9. 风险与回滚

- **风险**：声明性 spec 形式别扭（无实现），未来会话可能困惑"S238 要实现什么"。**缓解**：§1/§5 明确标注"声明性归档，非实现性"。
- **回滚**：删 `specs/S238-daban-workflow-archive/` 目录即可（纯文档，无代码副作用）。`docs/daban-workflow.md` 保留（手艺参考价值不依赖 spec）。
