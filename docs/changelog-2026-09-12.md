# 本轮改动总结 · 2026-09-12

> 24 commit（9-12），覆盖飞书 bot/LLM/数据基建/缺口理论/实盘通道/验证方法论 6 域。
> 目的：让本轮代码改动可追溯（哪个模块改了什么/为什么/commit hash），避免"代码做了没文档"的隐性知识。

## 1. 飞书 bot + LLM + 公网入口（5 commit）

| commit | 模块 | 改动 | 为什么 |
|---|---|---|---|
| `5e2bc9f` | `routers/feishu_bot.py` + `chat.py` | 飞书 bot 回复走 BOT app App Bot（load_config 替 Config 不读 env + BOT app 凭据 + prefer_app_bot 强制）+ LLM 主备 failover（_get_env_llm_config 附 backup_cfgs + _call_llm 主失败切备） | 飞书 bot 之前回复走通知 app webhook（用户收到错 app）+ LLM 主端点 Tailscale relay 抖（RemoteDisconnected） |
| `ab22f4e` | `chat.py` | 补 `logger` 定义（_call_llm failover 的 logger.warning 缺 logger 致 NameError） | 主端点失败切备时 NameError 被 feishu_bot except 捕"对话失败: name logger is not defined" |
| `aa605dd` | `data/sources/stoke_src.py` | cls_telegraph 直连 akshare + 180s timeout + 2 retry + 容错（RB-10a） | akshare 财联社电报接口超慢（真根因 404 废弃，容错不炸） |
| `5209054` | backlog | RB-10 真根因（akshare 接口 404 废弃，非超时） | subagent 二次实测纠正原诊断 |
| `cc8ce22` | backlog | RB-10 拆 RB-10a（容错 done）+ RB-10b（换源待办） | 拆分容错 vs 换源 |

**飞书 bot 现状**（memory `feishu-bot-reply-app-config`）：回复走 BOT app App Bot API（不走通知 webhook）+ LLM 主 192.168.2.156/v1 kimi-k2.6[1M] + 备 100.87.96.116/v1 glm-5.2（chat.py _call_llm failover）。cloudflared root launchd 守护（`vibe.myassi.eu.cc`→:8900 公网入口，memory `cloudflared-tunnel-daemon`）。healthchecks.io cron 心跳（RB-2 done）。

## 2. 数据基建 datalake（5 commit）

| commit | 模块 | 改动 | 为什么 |
|---|---|---|---|
| `869e3f4` | `scheduler/executors/data_ops.py` | daily_full_pull 补 reports key（遍历首板 codes 拉研报）+ news/pe_pb 静默吞错改 logger.warning | subagent B 实测 datalake 四源断（reports 从未拉 + 静默吞错） |
| `701059a` | `tools/mootdx_tick_ofi_proxy.py` + `data_ops.py` | ticks raw 沉淀——proxy 加 `--save-datalake` 模式直接落 datalake（不经 stdout 大 JSON）+ daily_full_pull 改单次 subprocess 多 codes | RB-11——proxy 原只输聚合不输 raw，save_ticks 从未调→ticks_YYYYMM.db 不存在 |
| `1d85f57` | backlog | RB-10/11 follow-up 落 | 确定待办记入 |
| （S191 datalake 已实现）| `data/datalake/replay.py` + `store.py` | datalake 回放引擎 + 存储层（之前 commit，本轮实测确认） | RB-3 datalake 基建 |

**datalake 五源现状**（memory 无——这是代码层）：reports ✅（517/9-11）/ strong ✅（90）/ pe_pb ✅（2）/ ticks ✅（4525/股 raw）/ news ⏳（akshare 接口 404，容错不炸，RB-10b 换源待办）。回放引擎 `replay_day(date, codes)` 可用。

## 3. 缺口理论集成（5 commit + 3 spec）

| commit | 模块 | 改动 |
|---|---|---|
| `340ed73` | specs S193/194/195 | 缺口理论集成 spec 草案（grill-me 17 轮 Q1-Q17 定向：缺口作 regime 信号不直接买卖 + 喂 AI 研判 + 不验单信号 §44 验融合消融）|
| `6386e99` | `engine/gap_classifier.py` + `tests/test_gap_classifier.py` | S193 classify_gap 纯函数实现（四类缺口分类 + 11 测试全绿）——量比≥2.0+3日不回补+20日前高（§44 sweep 空间）|
| `895af71` | specs S193/194 | spec grill 6 真问题全修（§1.1 multifactor null 对账 + F3 event edge + FS1 不过§44 + F1 功效约束 + R5 分负信息 gate + §4 复用 multifactor）|
| `ef2cde7` | specs S194/plan.md | plan——5 模块拆分 + 依赖序 + minimal 先 |
| `a042d34` | specs S194/tasks.md | 13 原子任务（Phase 3a minimal 验证闭环 → 3b AI 研判层）|

**缺口理论现状**：classify_gap 函数 done（`engine/gap_classifier.py` 180 行 + 11 测试绿）。图谱实体 `Obsidian investing/strategies/gap-theory.md` + MOC 导航引。S194 spec/plan/tasks 三件套就绪，等实现 Phase 3a（signal_align + bayesian_signal_weight + ablation_runner，复用 multifactor OOS）。

## 4. 实盘通道评估（1 commit）

| commit | 模块 | 改动 |
|---|---|---|
| `eed29cc` | specs S192 + backlog | QMT 实盘通道评估定论——当前不开户（无 edge），先用同花顺 SuperMind 免费回测；有 edge 后国金 10 万开户 + miniQMT + Windows 网关 + xqshare 代理 |

**S192 定论**（memory `qmt-live-trading-channel-eval`）：miniQMT 10 万门槛（国金）+ xtquant Windows-only（macOS 走 xqshare 远程代理）+ 先 SuperMind 免费回测验证策略有 edge 再启动开户。

## 5. 验证方法论修正（4 commit + workflow）

| commit | 模块 | 改动 |
|---|---|---|
| `05f7e89` | memory | S193-195 spec grill 6 真问题落 memory（核证据后：5 真 + 1 证伪）|
| `5575562` | specs/_brainstorm/W1-2026-09-12.md | brainstorm W1 落盘（24 方案全 grill 毙=0 confirmed，synthesize 救回方向——本周聚焦 S194 融合基线）|
| `2cb8340` | backlog + memory | 技术分析信号源调研（S196 候选 MACD+RSI，子 agent A）|
| `ae801d6` | specs S171 | subagent A 前置 gate 验证后修正 spec 3 处（stock_value_em 单股接口 + sz.000405 非 0 bars + PIT 对齐子步骤）|

**方法论核心修正**（memory `gap-theory-integration` + `s193-195-spec-grill-findings`）：单信号 §44 不过 ≠ 融合无 edge（用户反思"融合才是正确思路"）——但 S194 须 engage 已证否的 multifactor null（`any_multifactor_edge=无` 高置信），不假设 AI-reasoning 融合有 edge。

## engine/ 模块职责表（本轮新增 + 改动）

| 模块 | 职责 | 本轮改动 |
|---|---|---|
| `engine/gap_classifier.py` | **新增**：缺口四类分类（classify_gap 纯函数 + 量比/回补/压力位判定） | 新建（`6386e99`，11 测试绿） |
| `engine/accounting.py` | 成本模型（_cost_pct + t0_cost） | t0_cost 改 T+0 专属（T0_SLIPPAGE_PCT=0.10% + COMMISSION_RATE_PCT，`8c6c01b`） |
| `engine/intraday_ofi.py` | OFI 计算 + ofi_turn_points 拐点 | （S189 之前加 ofi_turn_points，本轮未改） |
| `engine/trade_journal.py` | trade_journal 读写 | （未改，1092 rows 实测） |
| `engine/bars_provider.py` | baostock 日 K（fallback） | gap_classifier 外壳复用 `_baostock_a_share_hist` |
| `engine/paper_portfolio.py` + `drawdown_breaker.py` | bayesian_arm_size S180 + 回撤 breaker | （未改，S194 FS2 将延伸 S180） |
| `chat.py` | LLM 对话层 + TOOLS | _get_env_llm_config 加 backup_cfgs + _call_llm failover + logger 定义（`5e2bc9f`+`ab22b4e`） |
| `routers/feishu_bot.py` | 飞书 bot 回调 | load_config 替 Config + BOT app 凭据 + prefer_app_bot 强制（`5e2bc9f`） |
| `data/sources/stoke_src.py` | stoke 数据源 | cls_telegraph 直连 akshare + 180s+retry+容错（`aa605dd`） |
| `tools/mootdx_tick_ofi_proxy.py` | mootdx 分笔 OFI proxy | 加 `--save-datalake` 模式落 raw ticks（`701059a`） |
| `scheduler/executors/data_ops.py` | cron executor（daily_full_pull/healthcheck/brainstorm） | daily_full_pull 补 reports + 改静默吞错 + ticks 改单次 subprocess（`869e3f4`+`701059a`） |

## 工作流 + 后台任务产出（本轮）

- **spec grill workflow**（`wyilhd92b`，12 agent 626k tokens）：6 视角审 S193/194/195 spec，核证据后 5 真问题 + 1 证伪（1092 case 真实，grill agent 查错）→ 修 spec（`895af71`）
- **brainstorm W1 workflow**（`w1r96hu7i`，81 agent 4.3M tokens 3 小时）：8 专家 propose → 3 视角 grill → synthesize。24 方案全毙（confirmed=0，印证 `grill-doubt` memory），synthesize 救回方向——本周聚焦 S194 融合基线 + hithink key（stale，用户决定不换）+ forward_test 攒 30 天
- **子 agent A 技术分析调研**：S196 候选 MACD 背离 + RSI（P0 双子作 regime 信号 + 互补缺口 + 数据够）
- **subagent B datalake 实测**：replay 引擎可用 + 四源断诊断 → 修 RB-10/11
- **subagent A S171 前置 gate**：两 gate 过（akshare 历史 PE + baostock 退市覆盖），pipeline 可行

## 关联

- 各 spec：`specs/S189/S192/S193/S194/S195/S196/S171`
- memory：`feishu-bot-reply-app-config` / `llm-endpoint-failover-cc-switch` / `cloudflared-tunnel-daemon` / `qmt-live-trading-channel-eval` / `gap-theory-integration` / `ta-signal-candidates` / `s193-195-spec-grill-findings` / `env-file-backend-vs-root`
- 代码：`engine/gap_classifier.py`（新增）/ `chat.py`（failover）/ `routers/feishu_bot.py`（BOT app）/ `scheduler/executors/data_ops.py`（daily_full_pull）/ `tools/mootdx_tick_ofi_proxy.py`（--save-datalake）/ `data/sources/stoke_src.py`（cls_telegraph 容错）
