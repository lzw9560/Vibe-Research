# Spec: S230 — §44 v3 R4/R5 进生产 verify() 路径

> 状态：**DEFER（abandoned 2026-09-25）——3 视角 grill 推翻审查 H1 的 P0 判断**
>
> **grill synthesis**：
> - **Reality Checker: DEFER**——未来无新 edge（milestone pivot 冻结新 spec/基建 + A+B 方向不追求统计 edge + consecutive_relay falsified + 6 edge 全假），R4 helper 已在 explore 可手动调 + test 进 CI，成本>>收益，违背 S229 "不改 verify() 签名"设计决策
> - **爆炸半径: BLOCKED**——long_value_run.py:1193 硬编码白名单静默丢 filter_fn 参数 / limit_up_premium 强制 raise 500 / wire_verdict 不透传 / **方案 C（不改 signature，post_hoc_analysis 字段）爆炸半径零更好**
> - **R4 设计权衡: NEEDS WORK**——is_fake_edge 下游不读（白标，DIMENSION_LIFT_REGISTRY/lift_to_multiplier 只认 validation_status）/ R1 漏审（V1 根因 R1+R4 只修 R4）/ 70% 阈值 overfit consecutive_relay V1
>
> **审查 H1 标 P0 被 grill 推翻**：H1 说"R4 没进 verify() = 未来假 edge 复发 P0"，但未来无新 edge 经 verify()（冻结），P0 不成立。
>
> **解冻条件**（同时满足）：①项目解冻新 edge 探索（milestone pivot 解除）②有新 edge 经 verify() 生产路径 ③涉及涨停/momentum survivorship ④手动调 R4 helper 证明不足。
>
> **方案 C 记录**（未来解冻用）：不改 verify() signature，verdict 加 `post_hoc_analysis` 字段（dict），caller 拿 verdict 后自填 R4 结果，爆炸半径零。避免 long_value_run.py:1193 白名单 + wire_verdict 透传问题。
>
> 作者：claude  日期：2026-09-25

## 1. 问题 / 目标

consecutive_relay V1 +1.04% 假 edge 被 §44 v2 验证通过但 V2 offline 量化证否。S229 §44 v3 改进落地了 R1/R3/R4/R5 + A5 + spec 模板 §7.1，但 **v4 审查 H1 发现**：R4 `compare_filtered_vs_unfiltered_edge`（抓 V1 假 edge 的关键——filter 掉涨停股揭真 edge）**只被 `tools/explore_ranking_anomaly.py:109` 调用，verify() 从不调它**。R5 `limit_up_premium` 只是类型定义+窗口映射，verify() 内无特殊处理分支。

**后果**：未来经 verify() API 验证的新 edge 不会自动跑 R4 momentum 过滤审——正是 consecutive_relay V1 假 edge（涨停封板溢价）漏网的根因。§44 v3 本是防此覆辙，但 guardrail 没通电。

**目标**：R4 进 verify() 生产路径——未来任何 edge 经 verify() 验证时自动跑 R4 momentum survivorship 审，标注 is_fake_edge，防止 V1 式假 edge 复发。

## 2. 背景

- verify() 现状（verifier.py:173-511）：只实现 R5 window_sanity + R3 event_materiality_floor，R1/R4 未集成
- R4 helper 已存在（verifier.py:514 `compare_filtered_vs_unfiltered_edge`），逻辑正确（filter 掉涨停股揭真 edge）
- A5 回归脚本（s203_harness_v3.py + tests/test_s44_v3_r4.py）验 R1 抓 V1 假 edge 99.4%
- S229 spec line 49 "R5 不改 verify() 签名"是 R2 合并设计决策——但导致 R4 无生产调用路径
- v4 审查 H1：R4 dead code（只 explore 调，verify 不调），spec 验收"R1/R3/R4/R5+A5 已落地"overclaim

## 3. 需求清单

- [ ] R1 verify() 内调 R4 helper：verify() 接受可选 `filter_fn`/`is_zt_fn` 参数，内部调 `compare_filtered_vs_unfiltered_edge` 标注 is_fake_edge
- [ ] R2 向后兼容：旧 harness 不传 filter_fn 时，verify() 标"R4 未跑"警告（非 block），不破坏现有 harness
- [ ] R3 R4 失败是 warning 非 block：is_fake_edge=True 时 verdict 标"假 edge 风险"但不改 validation_status（设计权衡——R4 是审非 gating，S229 spec line 49）
- [ ] R4 verdict 返回值扩 is_fake_edge/filter_pct/contrib_pct 字段（非改 validation_status）
- [ ] R5 _EdgeType "limit_up_premium" verify() 内特殊处理分支：edge_type=limit_up_premium 时强制跑 R4
- [ ] R6 文档：verifier.py docstring + S229 spec 验收修订（"R4 进 verify"非"R4 已落地 helper"）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/s44_verifier/verifier.py` | verify() 加 filter_fn/is_zt_fn 参数 + 内部调 R4 + verdict 返 is_fake_edge；_EdgeType limit_up_premium 强制 R4 |
| `backend/s44_verifier/types.py`（如有）| verdict dataclass 扩 is_fake_edge/filter_pct/contrib_pct |
| `backend/tests/test_s44_verifier.py` | 加 R4 进 verify() 的 test（filter_fn 传入 → is_fake_edge 标注）|
| `specs/S229-s44-v3-anti-fake-edge/spec.md` | 验收修订：R4 "已落地 helper"→"进 verify() 生产路径" |

## 5. 设计方案

**方案 A（推荐）：verify() 加可选 filter_fn 参数**
- verify(edge, dates, ..., filter_fn=None, is_zt_fn=None)
- 内部：if filter_fn: 调 compare_filtered_vs_unfiltered_edge(obs, filter_fn, dates) → 标 is_fake_edge/filter_pct/contrib_pct
- 旧 harness 不传 filter_fn → 标"R4 未跑"warning，不破坏
- edge_type=limit_up_premium → 强制要求 filter_fn（否则 raise，防漏跑）

**方案 B（不推荐）：verify() 自动推断 is_zt**
- verify() 内自动算涨停股——但涨停定义因 edge 而异（close 涨停/open 一字/盘中触及），自动推断会错
- 不选：涨停定义应预注册（§7.1 R4），caller 传 filter_fn 更对

**取舍**：方案 A 向后兼容 + 爆炸半径可控（旧 harness 不破坏）+ 涨停定义 caller 传（灵活）。方案 B 自动但易错。

## 6. 验收标准

- [ ] A1 verify() 传 filter_fn 时返 is_fake_edge/filter_pct/contrib_pct
- [ ] A2 verify() 不传 filter_fn 时标"R4 未跑"warning 非 block（向后兼容）
- [ ] A3 edge_type=limit_up_premium 传 filter_fn 强制，不传 raise
- [ ] A4 test: filter_fn 传入 → is_fake_edge=True（V1 假 edge 场景）
- [ ] A5 test: 旧 harness 不传 filter_fn → 不破坏（verdict 正常返 + warning）
- [ ] A6 full suite green（4098+ 不 break）

## 7. 合规与工程底线自查

- [ ] 研判/推荐属系统能力（§1.1），用户可见输出挂轻量风险提醒
- [ ] 判断可复现：R4 helper 逻辑已验（A5 回归 test），禁臆造
- [ ] 用户私有数据未进 git
- [ ] 无新增东财端点（不涉 em_get）
- [ ] R4 是审非 gating（S229 设计权衡，不改 validation_status）——防"R4 block 致 verdict 误杀"

## 7.1 §44 v3 anti-fake-edge sanity

- [ ] R1 entry close 涨停价审：verify() 内 R4 filter 掉涨停股揭真 edge（caller 传 filter_fn）
- [ ] R3 exit 一字跌停审：已实现（event_materiality_floor）
- [ ] R4 涨停 vs 未涨停对比：本 spec 核心——进 verify()
- [ ] R2 窗口语义标注：edge_type=limit_up_premium 强制 R4
- [ ] A5 回归测试：tests/test_s44_v3_r4.py 已写（R1 抓 V1 假 edge 99.4%）

## 8. 测试计划

- `pytest tests/test_s44_verifier.py -v`（加 R4 进 verify test）
- `pytest tests/test_s44_v3_r4.py -v`（A5 回归）
- `pytest -m "not live"` full suite 不 break

## 9. 风险与回滚

- **爆炸半径**：verify() 被 34 文件引用——改 signature 影响所有 harness。方案 A 向后兼容（可选参数）降风险
- **回滚**：filter_fn 默认 None，旧 harness 行为不变；出问题 revert verifier.py 即可
- **R4 warning 非 block**：防 R4 误判致 verdict 误杀（R4 是审非 gating）
