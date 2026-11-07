# Spec: S236 — 机构资金延续组合（inst_dominant combo）可交易落地

> 🟠 状态：edge **降级**（2026-10-18 cache 污染审计 + 干净终判）。kline cache 56% 残缺致 53% 回测 picks 算错时段。**干净终判**（backfill 4455 股 + re-migrate 1322MB DB 后 re-audit）：原 spec +0.457%@T+2 **不成立**（干净 T+1 +0.104% p=0.13 不显著，WR 46.7%）；污染报的 T+10 +3.685% 峰值 **虚高 ~3x**（干净 +1.069%）。干净实情：T+5+ 有统计显著正 mean（峰 +1.209%@T+15），**但 median 全负 + WR<47% = lottery 结构**。**降级为"弱 lottery 长持有 edge"**——非原 spec 强短持 edge，但非零。当前不交易（弱 edge + lottery + 长持有不满足原可交易标准）。correct-period 45.9% 子集曾误判零 edge（子集别外推）。walk-forward OOS/R12 用污染 cache 须干净复跑。
> 作者：Claude（agent）  日期：2026-10-09
> 关联：[[inst-dominant-walkforward-oos-edge-confirmed-2026-10-07]] / [[inst-dominant-r12-size-matched-2026-10-07]] / [[inst-dominant-combo-tradable-2026-10-09]] / skill `inst-dominant-combo`

## 1. 问题 / 目标

inst_dominant walk-forward OOS edge-confirmed（8年 mean+0.390% p=0.0000），但 commander_runner.py:178 标"观察池非买入"——基于单只口径 lottery（WR36% median负）。组合化深化后发现：日组合口径 WR54.3% median正（解决 lottery），>80%纯化+nostop+top6 深化后 mean+0.457% WR54.9% 可交易。

**目标**：把 inst_dominant 组合化口径落地为可执行交易系统 + skill + §44 R3 60天前向复验机制。基础版已实盘起始（10-09 top6），进阶版（追高+外资+中价20-100 post-hoc）待复验。

## 2. 背景

- inst_dominant edge-confirmed：walk-forward OOS（train+0.426/test+0.345 衰减19%）+ R12 size-matched（alpha+0.6628% 非size premium）+ 跨 regime（2018-2024/2025-2026 都PASS）+ Bonferroni
- 组合口径深化（2026-10-09）：单只WR36% lottery → 日组合WR54.3% median正 → >80%纯化WR54.8% → nostop最优 mean+0.414% → top6 mean+0.457%
- 因子分层（post-hoc）：追高+0.586% > 抄底+0.238%（**证否"抄底"叙事，实际是机构资金延续**）；外资>中资；高价>50最好+0.725%但买不满1手；进阶版追高+外资+中价20-100 mean+0.879% WR56.0%
- 现有基础：commander_runner.py:load_inst_dominant_today() 候选生成 / _audit_lhb_inst_full.py 回测 / trade_journal.db 交易记录 / dragon_tiger_history.db 龙虎榜

## 3. 需求清单

- [ ] R1: skill 落地 `~/.claude/skills/inst-dominant-combo/SKILL.md`（基础版+进阶版）
- [ ] R2: 基础版候选生成：>80% + top6按机构金额 + T+1open→T+2close nostop
- [ ] R3: 进阶版候选生成：基础版 + change_rate>=0 + 外资>30% + close_price 20-100
- [ ] R4: trade_journal 记录（arm=inst_dominant, is_active=1, weight=1.0, exit_model_version=nostop_t2）
- [ ] R5: §44 R3 60天前向复验机制（累积实际收益 vs 回测 mean 基准，衰减→降权/停）
- [ ] R6: 数据管道稳定（baostock 假熔断修复：HALF_OPEN 手动 record_success 或绕过原生 API）
- [ ] R7: 龙虎榜 backfill 每日补全（datacenter 通，push2his 熔断不影响）
- [ ] R8: 飞书通知战法总结（send_feishu 卡片）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `~/.claude/skills/inst-dominant-combo/SKILL.md` | 新建（基础+进阶 skill，已落地） |
| `backend/tools/commander_runner.py` | load_inst_dominant_today 加 >80% 纯化 + top6 + 进阶版因子过滤（可选 mode） |
| `backend/tools/_audit_lhb_inst_full.py` | 加 top6 口径 + 进阶版因子分层回测函数 |
| `backend/data/sources/baostock_src.py` | ensure_login HALF_OPEN 卡住修复（加 reset 或 record_success 重试） |
| `backend/tools/backfill_dragon_tiger_history.py` | 每日 backfill 10-XX（datacenter 通） |
| `.vibe-research/trade_journal.db` | inst_dominant arm 记录（已建 arm_status is_active=1） |
| `feishu_daily_push.py` | send_feishu 战法总结卡片（已验证可用） |

## 5. 设计方案

**基础版**：复用现有 _audit_lhb_inst_full 回测（top6 nostop mean+0.457%@T+1）+ commander 候选生成 + trade_journal 记录。**退出 ~T+10 close**（T+n 矩阵峰值 +3.685%@T+10 net，8x T+1，2026-10-18 `_audit_inst_top6_tn.py` bug-free）。口径：LHB >80% → top6 按机构金额 → T+1 open 等权5% → **~T+10 close 卖** → nostop 扛过 T+2~T+4 谷底。

**进阶版**：基础版 + 三因子（change_rate>=0 追高 + 外资>30% + close_price 20-100）。post-hoc 优化，60天复验前 weight=0.5（不重仓），复验通过→weight=1.0。

**取舍**：
- 不选"追高+高价>50"双因子（mean+0.940%最高）——高价买不满1手（688498 1290元），实操受限。
- 进阶版用中价20-100（mean+0.879% 接近双因子最优 + 可实操）。
- 三因子不如双因子（因子重叠），不堆更多因子（YAGNI + 过拟合风险）。

## 6. 验收标准

- [ ] A1: skill SKILL.md 落地，含基础版+进阶版规则+stats+限制
- [x] A2: 基础版回测复现 mean+0.457%@T+1 WR54.9%（跑 _audit_lhb_inst_full.py）+ **T+n 峰值 +3.685%@T+10**（跑 _audit_inst_top6_tn.py，8x T+1，2026-10-18）
- [ ] A3: 进阶版回测复现 mean+0.879% WR56.0%（跑因子分层）
- [ ] A4: trade_journal inst_dominant arm 记录可读写（已建 arm_status is_active=1 weight=1.0）
- [ ] A5: §44 R3 60天复验机制定义（累积收益 vs mean 基准，衰减阈值→降权/停）
- [ ] A6: baostock 假熔断修复（HALF_OPEN 不卡死）
- [ ] A7: 龙虎榜 backfill 每日补全（datacenter 通）
- [ ] A8（涉及数据）：回测 mean 经 _audit_lhb_inst_full.py 复算确认，禁心算

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力（§1.1 私人助理新口径）；用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」
- [x] 判断可复现：回测 mean 经 _audit_lhb_inst_full.py 复算（+0.457%/+0.879%），禁臆造/心算
- [x] 涨停四池/连板股榜个股属公开榜单（LHB 公开数据），可呈现 code/name
- [x] 用户私有数据（持仓/trade_journal）在 .vibe-research 不进 git、未上传
- [x] 新增东财端点走 em_get() 限流（backfill datacenter 走 eastmoney_get）

## 7.1 §44 v3 anti-fake-edge sanity

inst_dominant 已过完整 §44 v3 验证（walk-forward OOS + R12 + Bonferroni，见 [[inst-dominant-walkforward-oos-edge-confirmed-2026-10-07]]）：

- [x] **R1 entry 涨停价审**：inst_dominant entry = T+1 open（次日开盘价），非涨停价买入。LHB 上榜股次日 open 非一字涨停（回测 open 价可成交）。不适用（非涨停价 entry）。
- [x] **R3 exit 一字跌停审**：nostop exit = T+2 close。若 T+2 一字跌停卖不掉→回测排除（compute 返 None if t2_close 缺）。已处理。
- [x] **R4 涨停 vs 未涨停对比**：inst_dominant 选股基于 LHB 机构占比，非涨停筛选。回测含涨停+未涨停 LHB 股，survivorship 已在 walk-forward OOS 验证（train/test 都 PASS）。
- [x] **R2 窗口语义**：edge 类型 = "机构资金延续"（机构在涨中买→次日延续），非涨停封板溢价/隔夜 gap。标注完成。
- [x] **A5 样本量**：基础版 1710日/25327 picks（n 足），进阶版 814日（n 足，>60日 underpowered 阈值）。
- [ ] **进阶版 post-hoc 校正**：进阶版因子在样本内挖掘，须 60天前向复验 + Bonferroni 按 n 因子校正（已标 post-hoc 风险，复验前 weight=0.5）。

## 8. 测试计划

- 单测：commander_runner.load_inst_dominant_today + >80%纯化 + top6 + 进阶版因子过滤
- 单测：_audit_lhb_inst_full top6 口径 + 因子分层回测函数
- 回测复现：基础版 mean+0.457% / 进阶版 mean+0.879%
- 集成：trade_journal inst_dominant arm 记录→exit→net_pnl 计算
- §44 R3：60天累积复验（衰减阈值→降权/停）

## 9. 实现状态（2026-10-09 主体完成）

- skill SKILL.md：✅ 已落地（基础版+进阶版，`~/.claude/skills/inst-dominant-combo/`）
- spec/plan/tasks：✅ 已落地（S236 草案+plan+tasks）
- R6 baostock 假熔断修复：✅ circuit_breaker.reset() + ensure_login 直连验证（T1/T2/T3 完成）。但 baostock 黑名单（10001011）——用户决策忽略用 hithink 多源（T3a 关闭，不阻塞：回测用 cache，实时走 hithink）
- R2/R3 commander 集成：✅ load_inst_dominant_today mode=basic/advanced（T4/T6 完成）
- R5 复验脚本：✅ inst_dominant_replay_check.py（保守规则+60天门槛，T7/T8/T9a 完成）
- R5 回测固化：✅ audit_top6_combo（T5 完成，复现 mean+0.457%/+0.875%）
- trade_journal inst_dominant arm：✅ 已建（is_active=1 weight=1.0），10-09 top6 已记录（6条 signal 浮盈+1.857%）
- 基础版实盘：10-09 建仓 top6（002384/688313/300684/600330/002614/000513），10-13 卖
- 进阶版：post-hoc 待 60天复验，复验前 weight=0.5
- 飞书通知：✅ send_feishu 战法总结卡片已发
- 相关 test：✅ 56 passed（commander/circuit/baostock/inst_dominant，改动没破坏）
- 剩余：T9b cron 接入（待12月首次够60天）/ T6a 诚实标注用户实盘口径未测（已标 spec/memory）
- **2026-10-18 T+n 矩阵修正**：`_audit_inst_top6_tn.py`（bug-free，修 `_audit_inst_tn_matrix.py` 的 off-by-one）跑出 top6 T+n 曲线——T+1 +0.457% gross（原 spec 口径，`audit_top6_combo` 复现）/ T+2~T+4 负谷底 / **T+10 +3.685% net 峰值（8x T+1，p=0.0000，n=6152）** / 平顶到 T+15。退出规则 T+2→~T+10，解锁 8 倍闲置 edge。实盘 caveat：纸面 +3.685% 经滑点/前置收割/lottery 大概率衰减。用户 10-09 真盘单 -7.49%@T+4（还在持有，左尾），守 10-23(T+9 near-peak) 卖不延 10-26(T+10 峰值)——discipline 守预设退出非二次调退出。journal 假数（phantom +1.857%）已修（`_fix_inst_1009_journal.py`，replay_check 现报真实 -7.49%）。详见 memory `inst-dominant-1009-live-trade-2026-10-17`
