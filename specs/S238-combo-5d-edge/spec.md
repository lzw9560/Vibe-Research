# Spec: S238 — combo-5d-edge 可交易落地（小盘+动量+gap rank top-20，5日持有）

> 状态：已实现（2026-10-21）——接线 + 测试全绿，剩 60天前向实跑（真 OOS，非阻塞）
> 作者：Claude（agent）  日期：2026-10-21
> 关联：[[combo-5d-edge-survivor-2026-10-20]] / spec S237（A组T+10 同模式，已证伪）/ S236（inst_dominant，已证伪）/ skill `combo-5d-edge`

## 1. 问题 / 目标

递归 §44 loop（轮1-7）找到项目迄今**统计最强**的短线 edge：combo（小盘+动量+gap rank）top-20 + 5日持有。过 walk-forward OOS + Bonferroni + 可交易（扣成本 top20 net +2.06%）+ R12 真选股 alpha（64% alpha t=11.94，非 size premium）+ regime 全过（2023-2026 alpha t>6，2026 最强）。

**目标**：把发现落地为可执行交易系统（信号生成 + trade_journal arm + skill），挂 weight 0.5 小仓前向验证 60 天。**不是上仓位交易**——是诚实地把"样本内发现的 edge"放到真 OOS（live forward）检验。

## 2. 背景

- **edge 来源**：递归 loop 轮1-7（2026-10-20）。轮3 combo walk-forward OOS survivor（test t=3.06），轮5 延长持有发现 5日可交易（net +0.40%），轮6 集中度发现 top20 net +2.06%（越集中越强），轮7 R12 确认真选股 alpha（64%，非 size premium）+ regime 全过（2026 alpha +1.84% t=8.18 最强）。
- **vs 已证伪**：inst_dominant / A组T+10 / consecutive_relay 全证伪（cache 污染 + wrong-period + lottery）。combo 是项目第一个过全维度的 edge。
- **数据**：baostock_kline_cache.db（干净，backfill 8年 + re-migrate 后，5248 股 8 年日 K）。combo 信号只用 open/close/prev_close/amount，全在 cache，**不走东财 em_get**（无防封需求）。
- **现有接线**（S237 同模式）：commander_runner.load_a_group_today() 是候选生成入口；inst_dominant_replay_check.py 已通用化（arm 参数，支持多 arm）；trade_journal arm 表（is_active + weight）。

## 3. 需求清单

- [ ] R1: 信号生成 `load_combo_5d_today()`——读 cache 当日全市场，算 rank(gap)+rank(today_ret)+rank(-amount)，返 top-20 code+score
- [ ] R2: trade_journal arm `combo_5d`（is_active=1, **weight=0.5** 试探非重仓, hold_days=5, version 冻结）
- [ ] R3: skill `~/.claude/skills/combo-5d-edge/SKILL.md`（战法定义 + edge 数字 + caveat + 退出规则）
- [ ] R4: 60天前向 replay_check（复用 inst_dominant_replay_check.py，arm=combo_5d；保守规则同 S236：<70%→weight 0.25；<30%或<0→停）
- [ ] R5: 回测复现脚本固化（_audit_combo_deep/r12 已有，spec 引用不重写）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/commander_runner.py` 或新模块 `backend/strategies/combo_5d.py` | 加 `load_combo_5d_today()`（Explore 确认入口位置后定） |
| `.vibe-research/trade_journal.db` | combo_5d arm 记录（is_active=1 weight=0.5） |
| `~/.claude/skills/combo-5d-edge/SKILL.md` | 新建 skill |
| `backend/tools/inst_dominant_replay_check.py` | 复用（已通用化），加 combo_5d arm 支持（若需） |
| `specs/S238-combo-5d-edge/` | spec + plan + tasks（本 spec） |

## 5. 设计方案

**信号公式**（冻结，复现 [[combo-5d-edge-survivor]]）：
- 每日全市场每只票：`gap = (open - prev_close)/prev_close`，`today_ret = (close - prev_close)/prev_close`，`amount` = 当日成交额
- 横截面 rank（归一 0-1），composite = `rank(gap) + rank(today_ret) + rank(-amount)`（-amount = 小盘高分）
- 取 top-20

**交易规则**：
- 入场：次日开盘（集合竞价限价，非市价——执行专家教训，避跳空割）
- 持有：5 个交易日
- 出场：第 5 日收盘卖（或次日开盘卖，spec 冻结 close-to-close 回测口径 → 实盘用 T+5 close 附近限价）
- 止损：**无**（回测用 nostop，stop 未测——YAGNI，先 nostop 跟踪，stop 留作回溯优化）
- 仓位：每只 2.5%（20 只总 50%），weight=0.5（试探），50% 现金
- 等权（非 score 加权——回测是等权，冻结口径）

**取舍**：
- nostop（stop 未测，先冻结回测口径）
- 次日开盘入场（非当日 close——实盘可执行，回测 close-to-close 口径微调，alpha 容错 +1.8% 空间够）
- top-20（非 top-50/100——top20 edge 最强 t=13.6 median+0.588%；容量小但 edge 强，试探仓正合适）
- weight 0.5（非 1.0——见 §7.1 test-set-selection 诚实 caveat）

## 6. 验收标准

- [ ] A1: `load_combo_5d_today()` 在指定历史日返 top-20，复现 _audit_combo_hold 的 picks（同 code 同 rank）
- [ ] A2: trade_journal combo_5d arm 可读写（is_active=1 weight=0.5 hold_days=5）
- [ ] A3: skill `combo-5d-edge/SKILL.md` 落地
- [ ] A4: replay_check arm=combo_5d 跑通（0 signal 提醒 <60 天门槛，待 60 天后实跑）
- [ ] A5: 回测复现（_audit_combo_deep/r12 引用，net +2.06% top20 2023-2026）

## 7. 合规与工程底线自查

- [x] 研判/推荐属系统能力（§1.1 私人助理）；轻量风险提醒「历史统计特征，市场有风险」
- [x] 判断可复现：edge 数字经 _audit_combo_deep.py / _audit_combo_r12.py 复算（R12 alpha +1.61% t=11.94），禁臆造/心算
- [x] 用户私有数据（trade_journal / 持仓）.vibe-research 不进 git（.gitignore）
- [x] 防封：combo 只读本地 cache，**不走 em_get**（无东财端点，无防封需求）✅
- [x] 涨停四池/个股：combo 不涉涨停榜单（全市场 rank），个股 code 呈现属客观

## 7.1 §44 v3 anti-fake-edge sanity（**关键诚实 caveat**）

⚠️ **test-set-selection 偏差**：combo 的 spec（哪 3 因子 / top-decile / 5日持有）是**在 2023-2026 test 集上迭代选出**的（轮3 选 combo 因 singles 在 test fail；轮5 选 5日 因 1/3日 在 test fail）。所以 test 集 t=11.94 是**乐观的**——test 被用于模型选择，不只验证。walk-forward 不算干净 OOS。

- [x] R1 entry 涨停价审：combo 入场=次日 open（非涨停价，全市场 rank 不限涨停）✅
- [x] R3 exit 一字跌停审：T+5 close 卖，一字跌停 compute 返 None 排除
- [x] R4 涨停 vs 未涨停：combo 全市场 rank（非涨停选股），survivorship walk-forward 已验
- [x] R2 窗口语义：edge="小盘动量短期延续"（5天），非涨停封板溢价
- [ ] **真 OOS = 60天前向 live**（test-set-selection 唯一解药）：weight 0.5 试探，accumulated alpha 对比 +1.5~1.8%/5day 基准，衰减→降权/停
- [x] R12 size-matched：alpha 64% t=11.94（非 size premium，已验）
- [x] regime 全过：2023-2026 alpha t>6（已验，2026 最强）
- [ ] **进阶 post-hoc 校正**：60天前向后跑 Bonferroni×（loop 试过的方法数）——当前不阻塞，前瞻数据到位后补

## 8. 测试计划

- 单测：`load_combo_5d_today(date)` 返 top-20，对历史日复现 _audit_combo_hold 的 top-decile picks（同 rank 顺序）
- 集成：trade_journal combo_5d arm insert→read→exit→net_pnl
- 离线：`pytest -m "not live"`（复用现有套件，加 combo_5d generator 测试）
- 手动：跑 `load_combo_5d_today()` 当日（2026-10-21 cache 最新日），看 top-20 是否合理（小盘+涨得多+高开）

## 9. 风险与回滚

- **test-set-selection**（见 §7.1）：edge 可能在 live 衰减（像 inst/A组）。缓解：weight 0.5 + 60天 replay_check enforce（非 reminder）+ <70%→0.25 / <30%→停。
- **容量**：top-20 小盘钱进不去多少。缓解：试探仓 50% 总，每只 2.5%，小盘流动性够。
- **小盘滑点**：0.4% 成本估可能偏低。缓解：alpha +1.8% 容错空间大；60天实测滑点校准。
- **2026 in-sample**：2026 数据参与了 loop 发现，不算干净前向。缓解：60天 live（2026-10 起）是真 OOS。
- **回滚**：arm is_active=0 即停；无破坏性改动（新模块 + arm 记录 + skill）。
