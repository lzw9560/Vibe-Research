# Spec: S098 — 首板流选股 §44 合规修复（select 不 auto-rank + 确认时间序）

> 状态：已实现 + 验收通过（2026-08-26）
> 作者：Claude 会话  日期：2026-08-26
> 级别：medium-small（后端 select_for_entry 排序键改 + notify 标签；不碰外部数据 / 不新增 AI 工具 / 不涉财务验算）
> 流程门：spec.md + issue 层单轮 review；直接 develop
> 依赖：S075 首板流（`grill-decisions.md` 评分体系权威）+ S076 多源实测（done）+ §44（不 auto-rank）+ 记忆 `first-board-grill`（08-18 KEY BUG）
> 关联：S094（战法 pipeline，不交叉）、§44（不 auto-rank gate）、记忆 `quant-mindset-solid-foundation`

## 1. 问题 / 目标

`first_board_position.select_for_entry`（first_board_position.py:62）按 9 维 `total` 降序取前 max_n（绿灯5/黄灯3/红灯0）auto-top-N 建仓——违反：
- spec §2.4（"按确认时间排序先确认先买"）
- §44（系统不该 auto-rank 横截面；§44 未验证 which-5 无差别）

记忆 `first-board-grill`（2026-08-18）KEY BUG 明示"未实现，待 spec"。

stance raw-shadow（§44 三族 8 月无 validated edge，首板流降级 raw-shadow，剔除不进生产，confirm/position 不真建仓）：select 不 auto-rank 是 raw-shadow §44 合规核心。

**目标**：select_for_entry 改按确认时间序（先确认先买，first_5_by_time 中性 tie-break）取前 max_n；total 保留作 `total_score` 字段（用户筛选参考，非系统排序键）；notify §44 标签对齐"确认时间序，非质量排序，§44 未验证"。

## 2. 背景

- `select_for_entry`（first_board_position.py:62-125）：行 90-91 `open_confirmed 已按 total 降序，取前 max_n`。open_confirmed 来自 `first_board_confirm.confirm_candidates`（行 260-309），顺序 = candidates 顺序（first_board_filter 按 total 降序产，first_board_filter.py:1369）。每项有 `timestamp`（行 301，仅开盘价缺失分支设——确认分支需补）。
- `execute_entry`（行 128）：记录建仓（entry_time + entry_price_actual），**系统不下单**（建仓 gate ii，记忆 `first-board-grill`"系统不下单红线"）——已合规（不真建仓），本 spec 不改。
- `notify_entry_ready`（行 152）：已有"9 维度评分未 validated 仅参考"标注（行 159），但 select 仍 auto-rank（矛盾）。
- 评分体系：以 `specs/S075-首板流/grill-decisions.md` 为权威（硬剔除固定底线 + 动态权重 4 档 + 不截断 + 用户自筛）——本 spec 不改评分，仅 select 不按 total 排序。
- §44：首板流 raw-shadow 站住（8 月 verdict，三族 <2x）；select auto-rank 违 §44"不找最好"。
- D7d 影子先行：execute_entry 记账供 ≥30 交易日 + 洞B-gate≥2x 验证才转真建仓（框架在 `routers/win_rate.py` shadow_comparison，W0 行动闭环对照）。

## 3. 需求清单

- [ ] R1 `select_for_entry` 改按 open_confirmed 的 `timestamp`（确认时间）升序排序取前 max_n（先确认先买）；不再按 total 降序
- [ ] R2 `total` 保留作 `total_score` 字段（用户筛选参考，非 select 排序键）；`entry_rank` 改确认时间序 1-based
- [ ] R3 `notify_entry_ready` §44 标签对齐："通过确认 N 只受 cap 取前5（确认时间序，非质量排序，§44 未验证）"，不"推荐/最好"
- [ ] R4 `first_board_confirm.confirm_candidates` 确认分支补 `timestamp`（行 301 仅缺失分支设——确认分支也补，作 select 排序键）
- [ ] R5 §44 safeguard：select 永不按 total auto-rank；前端总分筛选滑块（若有）钉 3 条（§44 未验证+n 标签 / 默认关 / 系统不 auto-select）——前端滑块本 spec 不实现（follow-up）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/first_board_position.py` | select_for_entry 改确认时间序（按 timestamp 排序取前 max_n）；entry_rank 时间序；total 保留作 total_score 字段；notify_entry_ready §44 标签对齐 |
| `backend/strategies/first_board_confirm.py` | confirm_candidates 确认分支补 timestamp（作 select 排序键） |
| `backend/tests/test_first_board_position.py`（或新增） | select 按时间序 + 不 auto-rank + total 保留测试 |

## 5. 设计方案

### 5.1 select_for_entry 排序键改

```python
def select_for_entry(open_confirmed, market_light):
    # 旧：open_confirmed 已按 total 降序，取前 max_n
    # 新：按 timestamp（确认时间）升序，先确认先买；total 保留作 total_score 字段
    light = (market_light or "").lower()
    max_n = POSITION_PARAMS[...]  # 绿5/黄3/红0
    # 按确认时间序（timestamp 升序，None 兜底排后）
    ordered = sorted(open_confirmed, key=lambda c: c.get("timestamp") or "￿")
    selected = ordered[:max_n]
    ...
    for rank, cand in enumerate(selected, start=1):
        out.append({..., "total_score": cand.get("total"), "entry_rank": rank, ...})
    return out
```

### 5.2 §44 safeguard + α 诚实口径

- select 不按 total auto-rank（total 仅作 total_score 字段供前端筛选）。
- notify_entry_ready α 诚实口径："通过确认 N 只受 cap 取前5（确认时间序，非质量排序，§44 未验证）"，**不"推荐/最好"**（first-5 不靠谱，说推荐=踩回 §44"找最好"陷阱）。验证后换"§44 validated lift Xx"。

### 5.3 关键设计决策

- **确认时间序 vs total 排序**：§2.4"先确认先买" + §44"不 auto-rank" → 确认时间序（first_5_by_time 中性 tie-break，§44 which-5 无差别）。
- **total 保留**：评分体系（grill-decisions.md）保留+精炼，作用户筛选非系统选股；select 不按它排序。
- **execute_entry 已合规**：系统不下单（建仓 gate ii），execute_entry 记账供 D7d 影子盘验证——本 spec 不改 execute_entry。
- **stance raw-shadow**：§44 无 edge，select 修复是合规非加 edge（不宣称 alpha）。

## 6. 验收标准

- [x] A1 select_for_entry 不按 total 降序 auto-top-N
- [x] A2 按确认时间（timestamp）序取前 max_n
- [x] A3 total 保留作 total_score 字段；entry_rank 时间序 1-based
- [x] A4 notify_entry_ready §44 标签"确认时间序，非质量排序"
- [x] A5 测试：select 按时间序 + 不 auto-rank + total 保留（含 timestamp 缺失兜底）
- [x] A6 离线全测绿（全量 2279 passed，1 pre-existing `test_spec_consistency` 硬编码 S066 非 S098；S098 零回归破坏）

## 7. 合规与工程底线自查

- [ ] 不臆造：select 按确认时间序（真实 timestamp），不臆造排序
- [ ] §44 不 auto-rank：select 不按 total auto-top-N（§44 gate）
- [ ] α 诚实口径：notify"确认时间序非质量排序，§44 未验证"，不"推荐/最好"
- [ ] 私有数据隔离：不改数据存储
- [ ] em_get 防封：不涉外部端点

## 8. 风险与回滚

- **stance raw-shadow**：§44 无 edge，select 修复是合规非加 edge（不宣称 alpha，不 pivot）
- 回滚：`git revert` S098 commit（select_for_entry 排序键改 + notify 标签）
- **follow-up**（不在本 spec）：
  - 前端总分筛选滑块 §44 safeguard 3 条钉（§44 未验证+n 标签 / 默认关 / 系统不 auto-select）
  - first_plate.md 卡片重写（停在 S058，3 处矛盾 runtime，被 strategy_tools 喂 chat/MCP/CLI）
  - T-1 自选观察推送 + 9:25 灯位 + 9:35 + T+1 复盘飞书多点通知
  - 转真建仓（D7d ≥30 交易日 + 洞B-gate≥2x 后）
