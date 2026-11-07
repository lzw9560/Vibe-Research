# Spec: S237 — A组 T+10 组合（机构跟庄长持有）可交易落地

> 🔴 状态：edge 证伪（2026-10-18 cache 污染审计，待干净数据复判）。kline cache 56% 残缺致 50.5% 回测 picks 算错时段，correct-period（28.8%）**负 edge**（T+10 -0.479% WR 39.2% p=1.0）。+0.989% / walk-forward +0.912%/+1.094% 全是 wrong-period 假数。**待 cache backfill 完成 + re-migrate + re-audit 干净终判**（backfill 后台跑中 2026-10-18）。arm a_group_t10 已 is_active=0（10-13 用户跳过）。当前不交易。
> 作者：Claude（agent）  日期：2026-10-09
> 关联：[[a-group-t10-walkforward-oos-edge-confirmed-2026-10-07]] / skill `a-group-t10-combo` / S236（inst_dominant combo，同模式）

## 1. 问题 / 目标

A组 T+10 walk-forward OOS edge-confirmed（train+0.912%/test+1.094%），但单只口径 lottery 极端（median-3% WR25.3% R6 stop）。组合口径深化后发现：日组合 nostop WR53.6% median+0.388%（解决 lottery），mean+0.989%（高于 inst_dominant +0.414%）。

**目标**：A组 T+10 组合口径落地为可执行交易系统 + skill + §44 R3 60天复验。用户选"接小仓试水"（10-13 买3只）。

## 2. 背景

- A组 T+10 edge-confirmed：walk-forward OOS（train+0.912/test+1.094 衰减-20%）+ 8步6/8 PASS
- 组合口径深化（2026-10-09）：单只 median-3% WR25.3% lottery → 日组合 nostop WR53.6% median+0.388% → mean+0.989%
- nostop 最优：-3% stop FAIL（mean+0.180% WR41.5% median负，割反弹有害）
- 持有8天（T+2~T+10）vs inst_dominant 1天，风险大
- 现有：commander_runner.py:load_a_group_today() / _audit_a_group_t10_r6_stop.py / _audit_a_group_t10_walkforward.py

## 3. 需求清单

- [ ] R1: skill 落地 `~/.claude/skills/a-group-t10-combo/SKILL.md`
- [ ] R2: 候选生成：load_a_group_today 加 mode（basic=top5 / combo=等权多只 nostop）
- [ ] R3: trade_journal 记录 arm=a_group_t10（已建 is_active=1 weight=1.0）
- [ ] R4: §44 R3 60天复验（同 S236 保守规则：<70%→weight 0.5；<30%或<0→停）
- [ ] R5: 数据缺处理（北交所920/hithink不识跳过）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `~/.claude/skills/a-group-t10-combo/SKILL.md` | 新建（skill，已落地） |
| `backend/tools/commander_runner.py` | load_a_group_today 加 mode |
| `backend/tools/_audit_a_group_t10_r6_stop.py` | 加 audit_a_group_combo nostop 组合口径函数 |
| `.vibe-research/trade_journal.db` | a_group_t10 arm（已建） |

## 5. 设计方案

**基础版**：A组 LHB（涨幅-3~+10%+净买<0.5亿+净买>0）→ T+2 open 等权买 → T+10 close 卖 → nostop。
**仓位**：每只8.3%（3只总25%），留75%现金（8天持有+nostop风险）。
**数据缺**：北交所(920)/hithink不识跳过（只买能查K线的）。
**取舍**：nostop（-3% stop FAIL）；持有8天（vs inst_dominant 1天，风险大但 mean 高）。

## 6. 验收标准

- [ ] A1: skill 落地
- [ ] A2: 组合口径回测复现 mean+0.989% WR53.6%
- [ ] A3: trade_journal a_group_t10 arm 记录可读写
- [ ] A4: §44 R3 60天复验（保守规则，同 S236）

## 7. 合规与工程底线自查

- [x] 研判/推荐属系统能力（§1.1）；轻量风险提醒
- [x] 判断可复现：回测 mean 经 _audit_a_group_t10 复算（+0.989%）
- [x] LHB 公开榜单，可呈现 code/name
- [x] 用户私有数据（trade_journal）.vibe-research 不进 git
- [x] em_get 防封（LHB backfill datacenter 通）

## 7.1 §44 v3 anti-fake-edge sanity

A组 T+10 已过 walk-forward OOS（train+0.912/test+1.094）：

- [x] R1 entry 涨停价审：entry=T+2 open（非涨停价，A组涨幅-3~+10%非涨停）
- [x] R3 exit 一字跌停审：nostop exit=T+10 close，一字跌停 compute 返 None 排除
- [x] R4 涨停vs未涨停：A组选股涨幅<=+10%（非涨停），survivorship walk-forward 已验
- [x] R2 窗口语义：edge="机构跟庄中期延续"（8天）
- [x] A5 样本量：2104日（n足）
- [ ] 进阶 post-hoc 校正：组合口径深化在样本内，60天复验定

## 8. 测试计划

- 单测：load_a_group_today mode
- 回测复现：audit_a_group_combo nostop mean+0.989%
- 集成：trade_journal a_group_t10 记录→exit→net_pnl

## 9. 实现状态（2026-10-09）

- skill SKILL.md：✅ 已落地
- trade_journal a_group_t10 arm：✅ 已建（is_active=1 weight=1.0）
- 组合口径回测：✅ 深化完成（nostop mean+0.989% WR53.6%，本次会话脚本）
- 用户10-13接入：**跳过**（3专家共识：跨2周末+8天nostop扛不住+regime可能牛市末期+资金调度冲突，用户改跳过），arm is_active=0 weight=0.0
- 剩余：load_a_group_today 加 mode（R2）/ audit_a_group_combo 固化（R2）/ 60天复验（R4，同S236保守规则）
