# Spec: S229 — §44 v3 anti-fake-edge（entry close 涨停 filter + realizability 单向 + momentum survivorship 审）

> 状态：**已通过**（2026-09-25 grill 4 视角 synthesis 修订后定稿；R1/R3/R4/R5 + A5 + spec 模板 §7.1 已落地实现）
> 作者：claude  日期：2026-09-24
> 关联：S159（§44 v2）、S228（consecutive_relay entry fix——废弃）、[[v1-fake-edge-retrospective-2026-09-24]]、[[consecutive-relay-falsified-2026-09-23]]、[[ofi-edge-exploratory-2026-09-24]]、[[seal-timing-fake-edge-2026-09-24]]

## 1. 问题 / 目标

consecutive_relay V1 +1.04% 假 edge 被 §44 v2 验证通过但 V2 offline 量化证否。盘中探索 3 edge（竞价/OFI/封板时机）全 V1 假 edge。**§44 v2 没抓到**——需 v3 改进。

## 2. 背景（V1 假 edge 真根因——grill synthesis 修正）

V1 假 edge 真根因**不是** realizability（一字涨停 sell 可成交——巨量买盘吞卖盘，持有人卖能立即成交）。真根因是：
1. **R2 窗口语义**：entry=D close=**涨停价**（连板日收盘封板涨停价）——买到涨停价，次日开盘高开是"涨停封板溢价"非"连板接力 edge"
2. **R4 survivorship**：只看涨停股（lbc≥2 连板 / price>=limit_up）——涨停股 next_open 连板高开，未涨停股无 edge（OFI 验证：涨停 +8.03% vs 未涨停 +1.05%）

**不是根因**（grill agent 2 F1 修正）：
- ~~R3 一字涨停 sell 卖不掉 over-credit~~——一字涨停 sell-side FILLABLE（巨量买盘吞卖盘），不是 over-credit

## 3. 需求清单（grill synthesis 修订）

- [x] R1：entry/exit 可交易性审——**close 涨停价 filter**（V1 entry=D close 涨停价，非只 open 一字）+ 复用 bar_utils 现有 detector（board-aware pctChg）
- [x] R2：窗口语义审——**合并 R1+R4+R5**（不独立 classify_edge_semantic，避免三套分类打架）。R5 _EdgeType 扩 "limit_up_premium"
- [x] R3：realizability-bias **单向**（删 is_onebuy_locked——一字涨停 sell 可成交）。保留现有 is_onesell_locked（一字跌停 sell 不可，已有）
- [x] R4：momentum survivorship 审——**R1 必要补充**（R1 不够抓盘中封板，R4 filter 涨停股）。涨停定义预注册（收盘涨停/盘中触及/一字/炸板）+ 并入 v2 窗口 sanity（4 合 1 前置审）+ filter 后样本量 check（n<60 underpowered）+ 泛化所有 momentum filter（涨停/lbc/一字/ST）
- [x] R5：§44 spec 模板加 v3 sanity 步骤

## 4. 受影响文件（grill synthesis 修订）

| 文件 | 改动 |
|---|---|
| `backend/s44_verifier/verifier.py` | R5 _EdgeType 扩 "limit_up_premium" + R4 compare_filtered_vs_unfiltered_edge（filter 前后对比 + 样本量 check） |
| `backend/strategies/journal_recorder.py` | R3 保留 is_onesell_locked（现有），**不加 is_onebuy_locked**（一字涨停 sell 可成交） |
| `backend/engine/bar_utils.py` | **不改**（复用现有 is_unbuyable_next_bar + is_onesell_locked_next_bar，board-aware pctChg） |
| `specs/_template.md` | R5 v3 sanity 步骤（entry close 涨停 + 涨停 vs 未涨停对比 + 样本量 check） |
| `backend/tools/s203_consecutive_relay_harness_v3.py` | A5 回归测试（V1 + R1 close 涨停 filter + R4 对比） |

## 5. 设计方案（grill synthesis 修订）

### R1：entry/exit 可交易性审（close 涨停价 filter + 复用 detector）

- **entry close 涨停价 filter**（V1 根因 1）：close vs prev_close 涨跌幅 >= board 阈值（主板 9.8%/创业板 19.8%/科创板 19.8%/北交 29.8%）→ entry close=涨停价买不到
- **复用 bar_utils**（agent 2 F2）：`is_unbuyable_next_bar(bar, code)` 判 entry 一字涨停（四价相等 + pctChg>=board）；`is_onesell_locked_next_bar(bar, code)` 判 exit 一字跌停
- **不发明新逻辑**——删 spec §5 "open vs prev_close>=9.5%" 近似（board 错：创业板 20% 股用 9.5% 漏判）

### R2：窗口语义审（合并 R1+R4+R5，不独立）

- **不独立 classify_edge_semantic**（agent 3 F1+F3）——避免与 R5 edge_type 三套分类打架
- R5 `_EdgeType` 扩 "limit_up_premium"（涨停封板溢价）——R5 已有 edge_type 枚举，扩一个值，不改 verify() 签名
- R1 filter 时标 "entry=涨停价" 警告 + R4 对比时标 "edge 集中涨停股" 警告（R1+R4 标注覆盖 R2 独立价值）

### R3：realizability-bias 单向（删 is_onebuy_locked）

- **删 is_onebuy_locked_next_bar**（agent 2 F1 CRITICAL）——一字涨停 sell-side FILLABLE（巨量买盘吞卖盘，持有人卖能立即成交），不是 over-credit
- **保留 is_onesell_locked_next_bar**（现有，一字跌停 sell 不可）
- _resolve_gap_exit 不加涨停 filter（一字涨停 exit=open 涨停价可成交）

### R4：momentum survivorship 审（R1 必要补充 + 涨停定义 + 并入 v2 + 样本量 + 泛化）

- **R1 必要补充**（agent 2 F3）——R1 filter entry 一字涨停不够（V1 假 edge source 是盘中封板 D close 涨停非一字），R4 filter 涨停股是唯一抓 V1 假 edge 机制
- **涨停定义预注册**（agent 1 F1）：收盘涨停（close>=limit_up）/ 盘中触及涨停（any ts price>=limit_up）/ 一字涨停（四价=涨停价）/ 炸板股（触及涨停但收盘未涨停）——4 类分别审 edge
- **并入 v2 窗口 sanity**（agent 1 F2）——4 合 1 前置审：窗口时机 + entry/exit 可交易性 + 窗口语义 + momentum 过滤审
- **filter 后样本量 check**（agent 1 F3）——filter 后 n<60 或 days<60 标 underpowered，不出 definitive verdict
- **泛化所有 momentum filter**（agent 1 F4）——涨停/lbc/一字板/ST 等任何 selection filter 都需 filter 前后 edge 对比

### R5：spec 模板 v3 sanity 步骤

`specs/_template.md` §44 自查栏加：
- entry close 涨停价审（close vs prev_close >= board 阈值？）
- 涨停 vs 未涨停对比（R4 momentum 过滤审）
- filter 后样本量 check（n>=60 / days>=60）

## 6. 验收标准

- [x] A1：verifier.py R5 _EdgeType 扩 "limit_up_premium" + R4 compare_filtered_vs_unfiltered_edge
- [x] A2：_resolve_gap_exit 保留 is_onesell_locked（现有），不加 is_onebuy_locked（一字涨停 sell 可成交）
- [x] A3：R1 复用 is_unbuyable_next_bar（entry 一字涨停 + close 涨停价 filter）
- [x] A4：specs/_template.md v3 sanity 步骤
- [x] A5：s203_harness_v3.py 回归测试——V1 + R1 close 涨停 filter + R3 一字跌停 + R4 对比，验收 R3+R1 filter 后 V1 edge < +0.3% + R4 标"filter 掉的 picks 贡献 >70%"
- [x] A6：full suite 0 failed
- [x] A7：grill 已过（4 视角 synthesis 修订）

## 7. 合规与工程底线自查

- [x] 判断可复现——verifier 代码可复算
- [x] 不臆造——v3 改进基于 V1 假 edge 根因实证 + 3 盘中 edge 验证
- [x] 私有数据隔离 / 防封——不涉

## 8. 测试计划

- s203_harness_v3.py 回归测试（A5）
- full suite pytest -m "not live"（0 failed）
- 用 v3 改进重审 OFI edge（涨停 vs 未涨停——验证 R4 抓假 edge）

## 9. 风险与回滚

- R-1（中）：R4 filter 后样本小（OFI 未涨停 n=34）→ underpowered 标注，不出 definitive
- R-2（低）：R3 不加 is_onebuy_locked——但一字涨停 exit 高 open 是真成交非 over-credit，R3 单向（一字跌停）够
- R-3（低）：_resolve_gap_exit 改后 settle_pending 重算 49 条 consecutive_relay 记录（已 archive，重算诚实标注）
- 回滚：git revert + verifier.py 回旧逻辑

## 10. grill synthesis（4 视角 16 finding 修订）

- agent 1（R4）：涨停定义预注册（炸板股漏网）+ 并入 v2 + 样本量 check + 泛化 momentum filter ✓
- agent 2（R1+R3）：**R3 删 is_onebuy_locked**（一字涨停 sell 可成交 F1 CRITICAL）+ 复用 bar_utils detector + R4 必要补充 ✓
- agent 3（R2）：合并 R1+R4+R5（不独立 classify_edge_semantic，避免三套打架）✓
- agent 4（回归）：**R1 close 涨停价 filter**（V1 entry=D close 涨停 F1 CRITICAL）+ A5 s203_harness_v3.py ✓
