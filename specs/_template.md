# Spec: SNNN — <短标题>

> 状态：草案｜已通过｜实现中｜已实现(YYYY-MM-DD)｜已废弃
> 作者：  日期：YYYY-MM-DD
> 关联：（其他 spec 编号 / issue / 相关文件）
>
> 本文件命名为 `spec.md`，放在 `specs/SNNN-短标题/` 子目录下（命名/子文档约定见 `../README.md`）。
> 同目录可选附 `plan.md`（技术方案）/ `tasks.md`（任务拆分）/ `验收报告.md`（实现归档）；
> 互相引用用同目录裸名，跨 spec 用 `../SNNN-短标题/spec.md`。

## 1. 问题 / 目标
<为什么要做这个改动？当前痛点、用户场景、期望结果。一句话能说清就一句话。>

## 2. 背景
<相关架构定位（引用 ARCHITECTURE.md 的模块）、现状数据、约束。>

## 3. 需求清单
- [ ] R1 …
- [ ] R2 …

## 4. 受影响文件
| 文件 | 改动 |
|---|---|
| `backend/xxx.py` | … |

## 5. 设计方案
<怎么做。含取舍、备选方案为何不选。>

## 6. 验收标准
- [ ] A1 …
- [ ] A2（涉及数据的：跑 `~/tools/financial_rigor.py` / `report_audit.py` 验算通过）

## 7. 合规与工程底线自查（逐条确认）
- [ ] 研判/推荐/买卖时机属系统能力（2026-07-30 新口径，CLAUDE.md §1.1）；用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」
- [ ] 判断可复现：涉及数据的跑 `~/tools/financial_rigor.py` / `report_audit.py` 验算通过，禁臆造/心算
- [ ] 涨停四池/连板股榜个股属公开榜单客观事实（设计选择，可呈现 code/name）；聚合指标 vs 客观榜单分层仅作推荐，非硬约束
- [ ] 用户私有数据（持仓/研报/key）未进 git、未上传
- [ ] 新增东财端点走 `em_get()` 限流

## 7.1 §44 v3 anti-fake-edge sanity（2026-09-24 S229，防 V1 假 edge 覆辙）

consecutive_relay V1 +1.04% 假 edge 教训——任何 edge 验证须过 v3 sanity：

- [ ] **R1 entry close 涨停价审**：close vs prev_close >= board 阈值（主板 9.8%/创业板 19.8%/科创板 19.8%/北交 29.8%）→ entry close=涨停价买不到。复用 `bar_utils.is_unbuyable_next_bar`（四价相等+涨停一字）+ close 涨停判（非一字 close 涨停）。**不只 filter open 一字——V1 entry=D close 涨停价（盘中封板收盘涨停非一字）**
- [ ] **R3 exit 一字跌停审**（单向）：`is_onesell_locked_next_bar`（四价相等+跌停一字）→ exit 卖不掉。**一字涨停 sell-side 可成交**（巨量买盘吞卖盘）——不 filter 一字涨停（非 over-credit）
- [ ] **R4 涨停 vs 未涨停对比**（survivorship）：filter 掉涨停股后 edge 变化？若 filter 掉的 picks 贡献 >70% → 假 edge 标志（涨停封板溢价）。+ filter 后样本量 check（n<60 / days<60 → underpowered 不出 definitive）。涨停定义预注册（收盘涨停/盘中触及/一字/炸板股 4 类分别审）
- [ ] **R2 窗口语义标注**：edge 是什么效应？涨停封板溢价（entry close 涨停价 + exit 次日 open 高开）/ 连板接力 / 隔夜 gap（entry 市场价 close）。R5 `_EdgeType` 扩 "limit_up_premium"——不独立 classify_edge_semantic（避免三套分类打架），合并 R1+R4+R5 标注
- [ ] **A5 回归测试**：v3 filter 重审历史 edge——若 filter 掉 >70% picks → 假 edge 证据（如 consecutive_relay V1 99.4% 涨停 entry）

## 8. 测试计划
<pytest -m "not live" / 联网 / 手动验收步骤。>

## 9. 风险与回滚
<可能影响面、回滚方式。>
