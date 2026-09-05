# S149 — vibe-astock 语义吸收（4 阶段框架 spec）

> **状态：** ✅ 审核通过 + 实现完成（large，Phase 0 审计 ✅ + 终审 grill ✅ PASS + 多专家对抗审查 ✅ 9 confirmed 已落 spec 修订；**Phase 4+2+3 已实现 2026-09-05，Phase 1 YAGNI 关闭**——见 task.md P1-T0 判据）
> **日期：** 2026-09-04
> **级别：** large — 触碰外部数据源 + AI 提示词 + 交易信号，按 AGENTS.md 自动判 large
> **来源：** github.com/lzw9560/vibe-astock@3c3b7c8（Apache-2.0，fork of Vibe-Research）
> **审查记录：** Oracle 架构审查 1 轮（ora-1）+ grill 自查 1 轮（23 项发现，8 🔴 已处理）+ Phase 0 审计 ✅ + Oracle 审计审查 1 轮（1 🔴 + 7 🟠 已修正）+ 多专家对抗审查 1 轮（6 视角 finder × 3-lens 验证，9 confirmed 已落 spec 修订，详见 audit-report §7）

---

## 0. 前置事实

| 项 | 事实 | 来源 |
|---|---|---|
| 关系 | vibe-astock 是 Vibe-Research 的 fork（作者 Simon Lin），同源代码 | GitHub repo 元数据 |
| 许可证 | Apache-2.0 | LICENSE 文件 |
| 核心包 | `duanxian/`（40+ 模块，自带 data.py/fetchers.py/config.py/cli_llm.py 基建） | GitHub Tree API |
| 既有决策 | DEC-003 已将 vibe-astock 定位为"指标定义参照"——参照定义、不导入代码 | `specs/decision-log.md:69` |
| 本地状态 | 本工作区**无 vibe-astock 克隆** | `find` 验证 |

**⚠️ DEC-003 关系声明：** DEC-003 原文（`decision-log.md:56-75`）的立场是"外部工具只借范式不引平台"。本 spec 的"选择性语义吸收"与该立场存在张力——交易日志/journal 是范式+数据模型一起引入，不是纯范式借鉴。裁决：数据管线基建（data.py/fetchers.py）遵循 DEC-003"借范式不引"→ 丢弃；交易日志是独立功能模块（无 Vibe-Research 对应物）→ 作为"范式+模型"引入，理由是重写一个 32KB 的成交时序结算引擎没有信息增量，且 vibe-astock 的口径（移动加权平均/逐笔时序/持仓周期）是行业标准做法。此裁决需 Phase 0 审计确认 vibe-astock 的 requirements 无 GPL 传染后生效。

**⚠️ 本 spec 结构：** Phase 0 ✅ 已完成审计 + 终审 grill 通过。Phase 1–4 G 门已定稿。审计报告见 `audit-report.md`。

**⚠️ 数据路径硬约束：** 所有新数据路径必须经 `vr_paths.resolve_data_dir()`（默认 `<repo>/.vibe-research`，支持 `VR_DATA_DIR` 覆盖），禁止硬编码 `~/.vibe-research/*`。测试隔离靠 `VR_DATA_DIR`（`conftest.py:14` 已有此机制）。本 spec 下文所有路径写法均为逻辑路径，实现时一律走 `resolve_data_dir()`。

**⚠️ 版本锁定：** Phase 0 clone 时记录 vibe-astock 的 commit SHA，后续所有移植以该 SHA 为准。移植文件头注明 `from vibe-astock@<sha>`。

### 1.1 问题

Vibe-Research 的情绪指标体系（`market.py::_emotion`）已有：涨停家数/炸板率/封板率/晋级率/连板梯队/连板股清单。但缺失：

| 缺失指标 | vibe-astock 对应模块 | 价值 |
|---|---|---|
| **赚钱效应**（昨日涨停股今日中位数/翻红率/再涨停率） | `emotion_metrics.py` `money_effect()` | 涨停家数只是原料，中位数才反映"多数人体感" |
| **连板溢价**（昨日 2 板以上今日表现）⚠️按个股、不可聚合 | `emotion_metrics.py` `consec_premium()` | 高标承接度。**注意**：`market.py:166` 有"零个股名"契约，此指标天然按个股——聚合口径（均值/中位）进 `_emotion`，明细走独立路由 |
| **情绪周期定位**（10 日窗口内第几天/分位/走向） | `emotion_metrics.py` `cycle_position()` | `limitup_sti/models.py` 的 `STI_WEIGHTS` 已含 `prev_zt_performance`（权重 0.10）。Phase 0 已判定：概念重叠但计算不同，cycle_position 作 STIPhase 展示层补充，不进 AI context/journal 盖章 |
| **原始数据归档**（每日原始响应永不删除） | `archive.py`（10KB） | 口径改了还能重算历史 |
| **结构漂移检测**（数据源变 vs 市场变 vs 制度变） | `drift.py`（11KB） | 防止假断点被当成真信号 |
| **交易日志**（成交时序结算/在险资金/MFE-MAE/归因） | `journal.py`（32KB）+ `at_risk.py` + `excursion.py` | "我自己做得怎么样"的记账本 |
| **可替换 Prompt 包**（analyst_style/judge_requirements/focus_model） | `prompts.py`（7KB） | 口径可替换，引擎不硬编码 |

### 1.2 目标

**选择性语义吸收**——不是整包引入 duanxian，而是：

1. 丢弃 duanxian 的重叠基建（data.py/fetchers.py/config.py/cli_llm.py/market_facts.py/reflection.py 等 37 个）——Vibe-Research 有更强版本。**trade_calendar.py 整体不引入，但 4 个函数（`is_settled`/`trade_dates_ending_at`/`live_quotes_are_close_of`/`quote_trade_day`）移植到 `vibe_astock_util.py`**（emotion_metrics 依赖，vr_paths 无等价物，见 audit §2.1）
2. 吸收 duanxian 的缺失逻辑（赚钱效应/连板溢价/情绪周期/归档/漂移/交易日志/PromptPack）
3. **移植 util.py**→`backend/utils/vibe_astock_util.py`（`atomic_write_json`/`china_now`/`china_today`/`validate_trade_date`，Vibe-Research 无等价物，6 个移植模块依赖它；`safe_join` 仅被丢弃模块消费，按 YAGNI 不移植）
4. 吸收时改写 import 指向 Vibe-Research 基建（`astock.py`/`data/sources/`/`chat.py`/`vr_paths`）
5. 保留 Apache-2.0 署名（`from vibe-astock@3c3b7c8`）

### 1.3 不做

- 不导入 duanxian 的 data.py / fetchers.py / config.py / cli_llm.py（基建重叠，Vibe-Research 有熔断器/防封/proxy_pool，更强）
- 不整包引入 `~/.duanxian-agents/` 数据目录（一次性迁移后废弃，不留双目录）
- 不导入 347KB 单体测试文件 `test_core_logic.py`（按模块 grep 提取对应测试）
- 不产生任何选股/买卖时机/参与倾向（守 AGENTS.md 工程底线）

### 1.4 范围冻结（防 scope creep，grill #22）

- **Phase 2 指标清单冻结**：赚钱效应/连板溢价/情绪周期三个，新增走新 spec
- **Phase 4 消费面冻结**：本期仅 chat.py，新消费方（debate/reflection 等）需新 spec
- **Phase 3 模块拆分已定**：journal.py + journal_risk.py（独立），不再"合入或独立"悬空
- **PromptPack 字段已定**：砍掉 focus_model/skeleton/render_focus 三件套，只保留纯文本风格字段

---

## 2. 阶段设计（重排后）

### Phase 0 — 审计（前置必做）

> Oracle 审查的核心结论：当前计划关于 duanxian/ 的一切描述在本工作区无法核实。必须先克隆 + diff。

**工作内容：**
1. `git clone https://github.com/lzw9560/vibe-astock` 到 `/tmp/vibe-astock`（不入仓库），**记录 commit SHA**
2. 全量 diff `duanxian/` vs Vibe-Research 对应模块，产出逐模块判定表：
   - `duanxian/emotion_metrics.py` vs `backend/market.py::_emotion` — 逐函数 diff，标注：吸收/参照/丢弃
   - `duanxian/emotion_metrics.py::money_effect()` vs `limitup_sti/models.py::STI_WEIGHTS[prev_zt_performance]` — **逐行对照**，判定语义重叠度
   - `duanxian/journal.py` vs `backend/portfolio.py` — 确认无冲突
   - `duanxian/prompts.py` vs `backend/chat.py` + `backend/llm_presets.py`（77行） — 确认接合点
   - `duanxian/archive.py` / `drift.py` — 确认全新无冲突
   - `duanxian/data.py` / `fetchers.py` — 确认丢弃（参照不导入）
   - **`server.py`（66KB）** — 提取路由端点清单（journal/drift 相关），Phase 0 审计表此前漏了此文件
   - **其余全部模块** — 默认丢弃，在 audit-report 中逐一列名确认
   - **核实模块总数**（spec 声称"40+"未经验证）
3. 检查 `requirements.txt` 许可证传染（GPL/AGPL 依赖）
4. **验证 archive.capture_day() 是否额外发网络请求**（§4 合规表有断言，`_fetch_prev_pool` 函数名暗示网络抓取）
5. **确认 Vibe-Research 复盘数据的真实存储位置**（Phase 3 改写目标 `reflection._load_review` 已验证不存在——`reflection.py` 72行只有 `run_reflection_stream`，无复盘数据加载函数；真实位置可能在 `daily_review.py`/`snapshot_store.py`/`routers/review.py`）
6. 产出 `audit-report.md`，含逐模块判定表 + 署名清单 + commit SHA + 上述验证项结果

**验收门：** audit-report.md 过 Oracle 1 轮审查

### Phase 4 — Prompt Pack 试点（最先做）

> 7KB、无硬依赖、隔离性好——验证吸收机制成本最低的试金石。

**工作内容：**
1. 在 `backend/chat.py` 的 `SYSTEM_PROMPT` 之上加一层 `PromptPack` 接口
2. 移植 `duanxian/prompts.py` 的 `PromptPack` dataclass + `RESEARCH_PACK` 默认包
3. **字段×消费点映射表：**

   | PromptPack 字段 | 接线到 | 本期是否接线 |
   |---|---|---|
   | `analyst_style` | chat.py SYSTEM_PROMPT 的分析框架段 | ✅ |
   | `analyst_len` | chat.py SYSTEM_PROMPT 的篇幅约束段 | ✅ |
   | `judge_requirements` | 无消费方（属复盘裁判链路，Vibe-Research 无对应模块） | ❌ 暂不接线 |
   | `focus_model` (pydantic) | 无等价物（全仓无结构化输出模型） | ❌ **砍掉** |
   | `focus_skeleton` | 同上 | ❌ **砍掉** |
   | `render_focus` | 同上 | ❌ **砍掉** |
   | `chat_guidance` | chat.py SYSTEM_PROMPT 的个股约束段 | ✅ |

4. **本期 PromptPack 只保留纯文本风格字段**（analyst_style/analyst_len/chat_guidance），砍掉 focus_model/skeleton/render_focus 三件套——Vibe-Research 无结构化输出模型（已验证：无 schemas.py、无 response_format 用法），新建一个 pydantic 模型超出试点范围
5. 加载机制：`resolve_data_dir()/prompts_local.py`（经 vr_paths，不用硬编码 home 路径），importlib 加载，缺失/损坏→静默回落默认包并记日志
6. **本期消费面仅 chat.py**——新消费方（debate/reflection 等）需新 spec
7. 署名头：`# derived from vibe-astock@<sha>, Apache-2.0, modified`

**验收门：** 默认包加载成功 + 本地包替换成功 + chat.py 原有行为不回归

### Phase 2 — 情绪指标扩展（最大冲突区，先做冲突审查）

> Vibe-Research 已有 `limitup_sti/`（STI 8 维情绪温度 + STIPhase 状态机）、`sentiment_context.py`（266行）、`weather_history.py`（76行）。必须先审查冲突再决定吸收还是原生扩展。

**冲突审查表（Phase 2 强制）：**

| 旧 spec R-item | 旧决策 | 新决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| S133 `emotion date-keyed cache` | 待实现：_emotion 按 date-keyed 缓存 | Phase 2 需在此基础上扩展 | **前置依赖** — S133 作为 Phase 2 前置 medium spec 独立先做，Phase 2 启动条件写死"以 S133 ✅为入口门" | S133 的缓存机制直接服务 Phase 2 新指标 |
| S122 `emotion 周末门控` | ✅已实现：非交易日不查东财 | 不影响 | **共存** | 无迁移，Phase 2 新指标复用 S122 的守卫 |
| S130 `lianban_stocks or-0` | 待实现：price/pct/amount 零值归一 None | Phase 2 新指标若读 lianban_stocks 的 price/pct/amount 字段，需 S130 修复 | **显式并入 Phase 2** — 若新指标需要这些字段，对应修复作为 Phase 2 工作项 | 无迁移，Phase 2 新指标读 S130 修复后的字段 |
| DEC-003 `外部工具只借范式不引平台` | 外部工具借范式不引平台 | 交易日志作为范式+数据模型引入 | **裁决**（见 §0 DEC-003 声明） | 数据管线=范式借鉴→丢弃；交易日志=独立功能无对应物→引入 |
| `limitup_sti/` STI 8 维 | 已实现：STIPhase 状态机 + 8 维温度，`STI_WEIGHTS` 已含 `prev_zt_performance`(0.10) | Phase 2 的情绪周期是否与 STI phase 重叠？ | **Phase 0 已判定：展示层补充** | 概念重叠但计算不同（cycle_position 基于 3 硬指标归一化，STIPhase 8 维加权）。cycle_position 作 STIPhase 辅助读数，**不进 AI context、不进 journal 盖章** |
| `market.py:166` 零个股名契约 | _emotion 聚合口径零个股名 | 连板溢价天然按个股 | **分层处置** — 中位数类（可聚合）进 _emotion；按股明细走独立路由并显式标注含个股名、不接入 AI context | 聚合与明细分层，消费方明确标注 |

**工作内容（Phase 0 审计后定稿）：**
1. 赚钱效应 `money_effect()` — 移植 `emotion_metrics.py` 的中位数/翻红率/再涨停率
2. 连板溢价 `consec_premium()` — 移植昨日 2 板以上今日表现。**分层处置**：聚合口径（均值/中位）进 `_emotion`，按股明细走独立路由并显式标注含个股名、不接入 AI context（守 `market.py:166` 零个股名契约）
3. 情绪周期 `cycle_position()` — **先 diff vs `limitup_sti/STIPhase`**，重叠判据："同一输入数据 + 同一计算语义 = 重叠 → 只在 STI 之上做展示层衍生，不新建数据管线"。重叠则参照不移植
4. 改写 import：`from .fetchers import ...` → `from data.sources.eastmoney import ...` / `from data.sources.tencent import ...`
5. 改写 import：`from .data import ...` → `from astock import em_zt_topic_pool, ...`
6. **前端展示**：新指标展示挂既有页面（Sentiment Weather 页或 Market 页），不新建页面。挂载点 = `routers/limitup/metrics.py`（Phase 0 审计已定死）
7. **若新指标读 lianban_stocks 的 price/pct/amount 字段**：S130 对应修复作为 Phase 2 工作项
8. **改写 `batch_pct()` 内联 urllib 裸调**（`emotion_metrics.py:7,29-55` 访问 `qt.gtimg.cn`）→ `data/sources/tencent.py::fetch_raw(codes)`，提取 `change_pct` 字段（audit §2.1 识别——它不是 import 是内联调用，工作项 4/5 够不着它）
9. **从 `trade_calendar.py` 移植 4 函数**（`is_settled`/`trade_dates_ending_at`/`live_quotes_are_close_of`/`quote_trade_day`）到 `vibe_astock_util.py`，基于 `vr_paths.is_trading_day` 实现（emotion_metrics 依赖，vr_paths 无等价物）

**启动条件：** S133（emotion date-keyed cache）✅ 已实现

**验收门：**
- 新指标输出带口径说明
- 不与 STIPhase 语义冲突（判据见工作项 3 + Phase 0 diff 结果）
- `pytest backend/tests/` 全绿（记录 Phase 2 启动前基线通过数，启动后不低于该数）

### Phase 3 — 交易日志（隐私边界测试先行）

> AGENTS.md 硬约束：个人交易数据不接入 AI prompt。vibe-astock 有测试锁住这条边界。

**工作内容：**
1. **先移植边界测试**（红灯先行）：从 `test_core_logic.py` grep `journal` / `prompt` / `private` 提取相关测试，移植为 `backend/tests/test_journal_privacy.py`，改接 Vibe-Research 基建
2. 移植 `journal.py`（32KB）→ `backend/journal.py`
   - 改写：`_market_context()` 从 `reflection._load_review` 改读 Vibe-Research 复盘数据 — ✅ **Phase 0 + 多专家审查修正（critical #1）**：走 **daily_review 磁盘持久化层**（`precompute_daily` 落盘 JSON 到 `<VR_DATA_DIR>/daily-review/<date>.json`，`get_daily_review` 先读磁盘 fallback `generate_review`），**零网络盖章**。不走 `routers/review.py` 的 `get_daily_review()` 路由入口（它同步调 `generate_review` 打 4 次 `em_zt_topic_pool` + `_sentiment`，违背 `journal.py:14` 零网络契约）。不走 vibe-astock 的 `reflection._load_review`（那是 vibe-astock 自己的 532 行模块，非 Vibe-Research 的 72 行 reflection.py）。`snapshot_store.load_snapshot` 是盘前快照（语义是"预期"非"实际"），不用于盘后盖章
   - 改写：`_stock_context()` 从 `market_facts.pools` 改读 `astock.em_zt_topic_pool`
   - 改写：数据目录经 `vr_paths.resolve_data_dir()`（禁止硬编码 `~/.vibe-research/`）
3. 移植 `at_risk.py`（8KB）+ `excursion.py`（14KB）→ **独立模块** `backend/journal_risk.py`（不合入 journal.py——54KB 单文件是开倒车）
4. 新增路由 `backend/routers/journal.py` — ✅ **Phase 0 已提取端点契约**：journal 7 个端点 + risk 9 个端点（含请求体/响应格式），见 audit-report.md §3
5. `app.py` 注册新 router（现有 37 个 `include_router`，加 `journal` 和 `drift`）
6. 前端新增页面（React 19，路由 `/journal`）
7. **盖章字段清单**：Phase 2 的哪些情绪指标写入 journal 记录的 `market` 字段（依赖声明了但工作项未跟上）

**隐私边界硬约束（grill #4 修正：一跳→闭包扫描）：**
- `journal.py` 和 `journal_risk.py` 的 import 图中**不得出现** `chat.py` / `ai/tools/` / 任何 prompt 构建模块
- `chat.py` 的 context builder **不得引用** `journal` / `portfolio`（个人数据模块）
- **边界测试用闭包扫描**：从 chat.py 出发做传递 import 图（含 `ai/tools/` 全部注册模块），断言闭包内无 `journal`/`journal_risk`/`portfolio`（denylist 用显式字符串，不靠 `journal` 子串匹配——否则 `journal_risk` 命中不可靠）——而非只扫 chat.py 源码（一跳扫描抓不到 `chat.py → ai/tools/registry.py → stock_tools.py → journal` 传递链）
- **运行时测试补充**：调 `registry.execute()` 遍历所有注册工具，断言返回值不含个人数据字段
- 函数内惰性导入用 `ast.walk` 覆盖
- **测试隔离**：设置 `VR_DATA_DIR` 后新模块读写跟随该变量（与 `conftest.py:14` 一致）

**验收门：** 边界测试全绿 + 交易日志 CRUD + 在险资金计算正确 + 前端页面可用

### Phase 1 — 数据归档 + 漂移检测（视 Phase 2 需求决定去留）

> Oracle 指出：Vibe-Research 已有 `sti_timeline` 表 + `weather_history.py`——历史情绪数据已存在。若 Phase 2 的历史对比能用既有数据满足，Phase 1 可整体推迟（YAGNI）。

**去留判据（可测问题）：** Phase 2 定稿时，若任一历史对比需求的输入无法由 `sti_timeline`/`weather_history`/既有快照满足，则触发 Phase 1，否则关闭并在 task.md 记录理由。

**工作内容（若 Phase 2 证明需要）：**
1. 移植 `archive.py`（10KB）→ `backend/data/archive.py`
   - 改写：数据目录经 `vr_paths.resolve_data_dir()`/archive/（禁止硬编码 `~/.vibe-research/`）
   - 改写：`capture_day()` 的 `_SLUG_SOURCES` 指向 Vibe-Research 的数据源
   - ✅ **Phase 0 已验证**：capture_day 有两条网络路径（`_fetch_prev_pool` 裸调 akshare + `market_facts.pools` 三池连调）。修正：只消费当日已落盘缓存（定时任务排在主管线之后），`_fetch_prev_pool` 改走 `em_get`，`pools` 路径改读 `astock.em_zt_topic_pool` 缓存
2. 移植 `drift.py`（11KB）→ `backend/data/drift.py`
   - 改写：`_day_structure()` 从 `archive.get` + `market_facts.pools` 改读 Vibe-Research 基建（同上路径修正）
   - 改写：制度日历路径经 `vr_paths.resolve_data_dir()`/drift/
3. 新增路由 `backend/routers/drift.py` — ✅ **Phase 0 已提取端点契约**：archive 1 个 + drift 3 个端点（含请求体/响应格式），见 audit-report.md §3
4. **归档不碰活动读取路径**——执行机制：monkeypatch 文件写入测试，断言 archive/drift 运行一次只落在 `archive/`、`drift/` 子目录内，不碰 `first_board_scores_*.json` / `portfolio.json`

**验收门：** 归档原始数据不删除 + 漂移检测三类分开 + 不影响每日定时管线

---

## 3. 阶段顺序（重排）

```
Phase 0（审计）→ Phase 4（试点）→ Phase 2（冲突审查驱动）→ Phase 3（边界测试先行）→ Phase 1（视 P2 需求）
```

**重排理由（Oracle 建议）：**
- Phase 0 前置：计划建立在未经核实的分叉描述上，必须先克隆 + diff
- Phase 4 先做：7KB、无依赖、隔离性好——验证吸收机制（license/测试/冲突审查流程）成本最低
- Phase 2 居中：最大冲突区（S133/limitup_sti/STIPhase），先冲突审查再决定吸收还是原生扩展
- Phase 3 在 P2 后：隐私边界测试先行，交易日志需要 Phase 2 的情绪指标做"市场环境盖章"
- Phase 1 可能砍掉：若 Phase 2 历史对比能用既有 `sti_timeline`/`weather_history` 满足，归档系统延后

---

## 4. 合规自查（AGENTS.md §工程底线）

> ⚠️ grill #7 修正：依赖 duanxian 代码行为的断言降级为"待 Phase 0 验证的假设"，验证不过则该合规结论不成立。

| 底线 | 自查 | 验证状态 |
|---|---|---|
| 不臆造数据 | 赚钱效应/情绪周期是推算值，输出必须带口径说明；漂移检测的"制度 vs 市场"分类必须是规则型输出，不用 LLM 判断 | ✅ 可执行 |
| 私有数据隔离 | Phase 3 交易日志 × Phase 4 prompt pack × chat.py 三者交汇——journal 数据在 chat.py context builder/prompt pack/AI 工具调用面上结构性不可达（闭包扫描 + 运行时测试锁定，见 Phase 3 隐私边界） | ✅ 可执行 |
| em_get 防封 | 所有移植的抓取必须走 `astock.em_get` / `data/sources/transport.py` 既有防封设施 | ✅ 可执行 |
| archive 不额外发网络请求 | ✅ Phase 0 已验证：**断言不成立**。capture_day 有两条网络路径（_fetch_prev_pool 裸调 akshare + market_facts.pools 三池连调）。修正：capture_day 只消费当日已落盘缓存，定时任务排在主管线之后；_fetch_prev_pool 改走 em_get；pools 路径改读 astock 缓存 | ✅ 已验证+修正 |
| 交易信号 | judgment/execution 归因、异常收件箱输出保持描述性/机械性，参考 `market.py:1` 的"客观数据机械分档"口径，不产生建议性措辞 | ✅ 可执行 |

---

## 5. 许可证与署名

- 移植文件保留原版权/许可头，加 `# derived from vibe-astock (github.com/lzw9560), Apache-2.0, modified` 声明
- `specs/decision-log.md:69` 扩充来源谱系记录
- Phase 0 审计检查 vibe-astock 的 `requirements.txt` 无 GPL/AGPL 依赖

---

## 6. 测试策略

1. 按迁移的函数/模块名 grep 提取对应测试，移植为 `backend/tests/test_<module>.py`
2. **隐私边界测试最优先**：Phase 3 代码落地前移植，先红后绿
3. duanxian 自家基建（data.py/fetchers）的测试不移植——不采用那些代码
4. 判据：测我们移植的东西，不测我们参照的东西

---

## 7. 验收条件（G 门）

| 门 | 条件 |
|---|---|
| Phase 0 | audit-report.md 含 commit SHA + 逐模块判定表 + 路由端点清单 + 许可证检查 + archive 网络行为验证 + 复盘数据存储位置确认；Oracle 审查仅 🔴 阻断需修，🟠 进 backlog |
| Phase 4 | PromptPack 默认包加载 + 本地包替换 + 回落默认包 + `pytest backend/tests/` 全绿（不低于 Phase 4 启动前基线通过数） |
| Phase 2 | 新指标带口径说明 + 不与 STIPhase 语义冲突（判据见 Phase 2 工作项 3） + `pytest backend/tests/` 全绿（不低于 Phase 2 启动前基线通过数）。**启动条件：S133 ✅** |
| Phase 3 | 闭包扫描边界测试全绿（denylist 显式含 `journal`/`journal_risk`/`portfolio`）+ 运行时工具遍历测试全绿 + CRUD + 在险资金计算（从 `test_core_logic.py` 提取的数值用例作为 golden values）+ **盖章路径零网络**（monkeypatch `em_get` 断言 `_market_context` 调用链未触网）+ 前端页面 |
| Phase 1 | （若做）归档不删除 + 漂移三类分开 + monkeypatch 测试断言只落 archive/drift 子目录 + 不影响定时管线 |

---

## 8. 归档

本 spec 验收通过后执行收拢流程（AGENTS.md §spec 落地后自动收拢）：
1. task.md 勾选验收状态
2. spec.md 顶部状态改"✅已实现(日期)"
3. 归档到对应里程碑目录
4. 更新 `specs/MILESTONES.md`
5. 同步 `ARCHITECTURE.md` + `docs/` 受影响段落

---

## 附：Phase 0 审计判定表（已审计 ✅，commit 3c3b7c8）

| duanxian 模块 | 大小 | Vibe-Research 对应 | 重叠度 | 判定 | 理由 |
|---|---|---|---|---|---|
| **util.py** | 4KB | **无等价物**（已验证） | 无 | **移植**→`backend/utils/vibe_astock_util.py` | Oracle 🔴：6 个移植模块全依赖 atomic_write_json/china_now/validate_trade_date，Vibe-Research 无等价物 |
| emotion_metrics.py | 22KB | market.py::_emotion + limitup_sti/STI_WEIGHTS | 部分（晋级率/封板率有，赚钱效应/连板溢价/情绪周期缺） | **吸收缺失函数** | money_effect/consec_premium/cycle_position 移植；promotion_rates/ladder_gap 参照不移植（已有）；cycle_position 作 STIPhase 展示层补充 |
| journal.py | 32KB | 无（portfolio.py 是持仓不是交易日志） | 无 | **移植** | 全新功能 |
| at_risk.py | 8KB | 无 | 无 | **移植**→合入 `journal_risk.py` | 全新功能 |
| excursion.py | 14KB | 无 | 无 | **移植**→合入 `journal_risk.py` | 全新功能 |
| attribution.py | 8KB | 无 | 无 | **移植**→合入 `journal_risk.py` | 判断vs执行归因 |
| inbox.py | 9KB | 无 | 无 | **移植**→合入 `journal_risk.py` | 异常交易收件箱 |
| risk.py | 26KB | 无 | 无 | **移植**→合入 `journal_risk.py` | 风险宪法 |
| prompts.py | 7KB | chat.py SYSTEM_PROMPT + llm_presets.py(77行) | 部分（prompt 硬编码 vs 可替换） | **移植 PromptPack 接口**（砍 focus 三件套） | 加一层纯文本风格字段，不替换 |
| archive.py | 10KB | 无 | 无 | **移植**（视 P2 需求） | 全新功能；capture_day 双网络路径需修正（见 §4） |
| drift.py | 11KB | 无 | 无 | **移植**（视 P2 需求） | 全新功能 |
| data.py | 17KB | astock.py + data/sources/ | 高 | **丢弃** | Vibe-Research 有熔断器/防封，更强 |
| fetchers.py | 26KB | data/sources/eastmoney.py + tencent.py | 高 | **丢弃** | 同上 |
| config.py | 2KB | config.py + .env | 高 | **丢弃** | 同上 |
| cli_llm.py | 4KB | cli_runtime.py | 高 | **丢弃** | Vibe-Research 有 3 条 AI 出口，更强 |
| reflection.py | 532行 | reflection.py(72行，语义不同) | 高 | **丢弃** | vibe-astock 自己的复盘评估模块 |
| market_facts.py | 28KB | market.py + astock.em_zt_topic_pool | 高 | **丢弃** | Vibe-Research 有更强版本 |
| trade_calendar.py | 8KB | vr_paths.py | 高 | **部分移植**（4 函数→`vibe_astock_util`，模块整体不引入） | Vibe-Research 有 is_trading_day，但缺 is_settled/trade_dates_ending_at/live_quotes_are_close_of/quote_trade_day（emotion_metrics 依赖，见 audit §2.1） |
| server.py | 66KB | app.py + routers/ | 高（路由定义来源） | **提取路由端点后丢弃** | Phase 0 已提取 24 个端点契约（journal 7+risk 9+archive/drift 4+positions 2+Phase2 情绪 2，见 audit-report §3；positions 2 仅参考不移植） |
| 其余 25 个模块 | — | — | — | **默认丢弃** | audit-report §1.2 逐一列名确认 |
| **合计** | **49 个** | | | **11 个移植→7 目标文件 + 1 部分移植（trade_calendar 4 函数→vibe_astock_util）+ 37 丢弃**（详见 audit §1.1/§1.2） | |
