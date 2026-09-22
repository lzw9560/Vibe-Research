# S149 实现计划（plan）

> 基于 spec.md（已落 9 条多专家对抗审查修正）+ audit-report.md §7。
> Phase 0 ✅ 已完成。实现顺序 **Phase 4 → 2 → 3 → 1**。
> 级别 large——feature 分支 + TDD + grill + playwright 验收（AGENTS.md 分级工作流）。

---

## 0. 依赖与阻断分布（来自多专家审查 §7）

| 前置 | 状态 |
|---|---|
| S133（emotion date-keyed cache） | ✅ 已实现（353e53b）→ Phase 2 可启动 |
| Phase 4 前 | #5 util 函数清单已定（spec §1.2）+ #8 §6.4 stale 已修 → **Phase 4 可立即进** |
| Phase 2 阻断 | #3 trade_calendar 部分移植 + #6 工作项 8/9（batch_pct + trade_calendar 4 函数） |
| Phase 3 阻断（最重） | #1 critical daily_review 磁盘层 + #2 O1 文档 + #4 journal_risk 隐私 + #7 端点 + #9 app.py 37 |
| Phase 1 | 视 Phase 2 历史对比需求（YAGNI 判据） |

**critical #1 是唯一需代码设计决策的阻断项**，已定方案：daily_review 磁盘持久化层（precompute_daily 落盘 JSON + get_daily_review 先读磁盘 fallback generate_review）。

---

## 1. Phase 4 — PromptPack 试点（最先做，试金石）

> 7KB、无硬依赖、隔离性好。验证吸收机制（license/测试/冲突审查）成本最低。

### P4-T1 移植 vibe_astock_util.py
- 从 `duanxian/util.py@3c3b7c8` 移植 4 函数：`atomic_write_json` / `china_now` / `china_today` / `validate_trade_date`（`safe_join` 不移植，YAGNI——仅丢弃模块消费）
- 从 `duanxian/trade_calendar.py@3c3b7c8` 移植 4 函数：`is_settled` / `trade_dates_ending_at` / `live_quotes_are_close_of` / `quote_trade_day`（基于 `vr_paths.is_trading_day` 实现，spec §1.2 + audit §2.1）
- 目标：`backend/utils/vibe_astock_util.py`
- 署名头：`# derived from vibe-astock@3c3b7c8 (util.py + trade_calendar.py 4 函数), Apache-2.0, modified`
- **测试**（TDD 先行）：`backend/tests/test_vibe_astock_util.py`——8 函数单测（含 `is_settled` 边界：盘前/盘中/盘后/非交易日）
- 依赖：无
- 验收：8 函数单测全绿

### P4-T2 移植 PromptPack
- 从 `duanxian/prompts.py@3c3b7c8` 移植 `PromptPack` dataclass + `RESEARCH_PACK` 默认包
- **砍 focus_model / focus_skeleton / render_focus 三件套**（Vibe-Research 无结构化输出模型，已验证无 schemas.py/response_format）
- 目标：`backend/prompt_pack.py`
- 署名头
- **测试**：`test_prompt_pack.py`——默认包加载 + 字段（analyst_style/analyst_len/chat_guidance 纯文本字段）
- 依赖：P4-T1（同期，无直接依赖）
- 验收：PromptPack 加载 + RESEARCH_PACK 字段

### P4-T3 chat.py 接线 PromptPack
- `backend/chat.py` SYSTEM_PROMPT 之上加 PromptPack 接口
- `analyst_style` → `ANALYSIS_FRAMEWORK` 变量 hook（chat.py:36 已有 `{ANALYSIS_FRAMEWORK}` 插值点 line 70）
- `analyst_len` → 篇幅约束段 / `chat_guidance` → 个股约束段
- `judge_requirements` 暂不接线（属复盘裁判，Vibe-Research 无对应模块）
- **测试**：`test_chat_promptpack.py`——默认包 + 本地包替换 + 回落默认 + **chat 原有行为不回归**（记录 pytest 基线通过数，启动后不低于）
- 依赖：P4-T2
- 验收：默认包加载 + 替换 + 回落 + 不回归

### P4-T4 本地包加载机制
- 加载路径：`resolve_data_dir()/prompts_local.py`（经 `vr_paths`，不硬编码 home）
- importlib 加载，缺失/损坏 → 静默回落默认包 + 记日志
- **测试**：损坏包回落 + 缺失回落 + 日志记录
- 依赖：P4-T3
- 验收：**Phase 4 G 门**——默认包加载 + 本地包替换 + 回落默认 + `pytest backend/tests/` 全绿（不低于 Phase 4 启动前基线）

---

## 2. Phase 2 — 情绪指标扩展（S133 ✅ 可启动）

> 最大冲突区（limitup_sti/STIPhase）。冲突审查已过（spec §2 冲突审查表）。

### P2-T1 移植 emotion_metrics 缺失函数
- `money_effect()`——中位数/翻红率/再涨停率（多维度分布，STI 只取再涨停率一个数，不重叠 audit §2.3）
- `consec_premium()`——昨日 2 板以上今日表现。**分层**：聚合口径（均值/中位）进 `_emotion`，按股明细走独立路由 + 显式标注含个股名 + 不接入 AI context（守 market.py:166 零个股名契约）
- `cycle_position()`——作 STIPhase 展示层补充。**双源规则**：不进 AI context、不进 journal 盖章；前端同屏标注口径差异（STIPhase=主，cycle_position=辅）
- `build_metrics()` / `render_metrics()` / `day_summary()`
- 路由挂载点：`routers/limitup/metrics.py`（Phase 0 已定死）
- 目标：`backend/emotion_metrics_ext.py`
- **测试**：`test_emotion_metrics_ext.py`——各函数 + 口径说明输出 + cycle_position 不冲突 STIPhase
- 依赖：P4-T1（vibe_astock_util 的 trade_calendar 4 函数 + atomic_write_json）
- 验收：新指标带口径说明

### P2-T2 import 改写（4 点，audit §2.1 import 依赖表）
- **a. `batch_pct()` 内联 urllib 裸调**（emotion_metrics.py:7,29-55 访问 qt.gtimg.cn）→ `data/sources/tencent.py::fetch_raw(codes)`，提取 `change_pct` 字段（spec 工作项 8）
- **b. `fetch_prev_pool`**（惰性 :165）→ `astock.em_zt_topic_pool("getYesterdayZTPool", ...)` + **显式字段映射**（fetch_prev_pool 返回 ret/prev_boards/limit_price/close，em_zt_topic_pool 返回原始池行字段名不同——先列映射表，audit §2.1 已标⚠️）
- **c. `is_limit_up`**（惰性 :175）→ 基于映射后字段机械判定（close ≈ limit_price，定容差阈值）
- **d. `from .fetchers` / `from .data`** → `data.sources.eastmoney` / `astock`
- **测试**：字段映射单测 + 端到端（money_effect/consec_premium 真实取数）
- 依赖：P2-T1
- 验收：4 改写点全过 + 不裸调 urllib

### P2-T3 前端展示
- 挂既有页面（Sentiment Weather 页或 Market 页，读 frontend/src 确认存在），不新建页面
- cycle_position 双源标注（口径差异或主辅关系）
- **测试**：前端组件渲染（vitest）
- 依赖：P2-T1
- 验收：**Phase 2 G 门**——新指标带口径说明 + 不与 STIPhase 语义冲突 + `pytest` 全绿（不低于 Phase 2 启动前基线）

### P2-T4 S130 并入（条件）
- 若新指标读 `lianban_stocks` 的 price/pct/amount 字段 → S130 修复（零值归一 None）作为 P2 工作项
- 依赖：P2-T1（确认是否读这些字段）

---

## 3. Phase 3 — 交易日志（最重，隐私边界先行）

> AGENTS.md 硬约束：个人交易数据不接入 AI prompt。

### P3-T1 边界测试先行（红灯）
- `backend/tests/test_journal_privacy.py`：
  - **闭包扫描**：从 chat.py 出发做传递 import 图（含 `ai/tools/` 全部注册模块），断言闭包内无 `journal`/`journal_risk`/`portfolio`（denylist 用显式字符串，不靠 `journal` 子串匹配——spec Phase 3 隐私约束 #4）
  - **运行时测试**：`registry.execute()` 遍历所有注册工具，断言返回值不含个人数据字段
  - `ast.walk` 覆盖函数内惰性导入
- 从 `test_core_logic.py` grep `journal`/`prompt`/`private` 提取参照（原测试作参照不作成品，audit §6.2 🟠-8）
- **测试**：先红（实现前失败）→ 实现后绿
- 依赖：无
- 验收：红灯成立

### P3-T2 新建 daily_review 磁盘持久化层（critical #1，唯一代码决策）
- `precompute_daily` 落盘 JSON 到 `<VR_DATA_DIR>/daily-review/<date>.json`（经 `vr_paths.resolve_data_dir()`）
- `get_daily_review` 改：先读磁盘 → fallback `generate_review`（原网络路径）
- `_market_context()` 走磁盘层（**零网络盖章**）
- **不走** `routers/review.py:43 get_daily_review()` 路由入口（同步打 4x em_zt_topic_pool + _sentiment）
- **不用** `snapshot_store.load_snapshot`（盘前快照，语义"预期"非"实际"）
- **测试**：monkeypatch `em_get` 断言 `_market_context` 调用链未触网 + 磁盘读写 + fallback 路径
- 依赖：P3-T1（红灯先行）
- 验收：**盖章零网络**（G 门 monkeypatch em_get 断言）

### P3-T3 port journal.py
- `duanxian/journal.py@3c3b7c8` → `backend/journal.py`
- `_market_context()` 走 P3-T2 磁盘层 + `_stock_context()` 从 `market_facts.pools` 改读 `astock.em_zt_topic_pool` + 数据目录经 `vr_paths.resolve_data_dir()`
- **保留 `threading.Lock`**（journal.py:125，防"后写覆盖先写=静默丢单"，spec 审查 critical 旁系）
- import 图不得出现 `chat`/`ai/tools`（#4 隐私）
- **测试**：CRUD（add/update/delete）+ fills/fee 计算 + in-memory 锁
- 依赖：P3-T2

### P3-T4 port journal_risk.py
- `at_risk` + `excursion` + `attribution` + `inbox` + `risk`（5 个@3c3b7c8）→ `backend/journal_risk.py`
- ⚠️ 5 合 1 = 65KB ≈ 1625 行，**超 coding-style.md 800 行上限**——实现时量行数，超 800 则拆 2-3 模块（如 at_risk+excursion 一个、attribution+inbox 一个、risk 独立）。spec 已标"54KB 开倒车"风险，实现时若超限则拆分（spec Phase 3 工作项 3）
- import 图不得出现 `chat`/`ai/tools`（#4 隐私，与 journal.py 同约束）
- 闭包扫描 denylist 显式含 `journal_risk`（#4）
- **测试**：在险资金 golden values（从 `test_core_logic.py` 提取数值用例）+ MFE/MAE + 归因 + inbox
- 依赖：P3-T3

### P3-T5 路由 routers/journal.py
- journal 7 端点 + risk 9 端点（audit §3 契约）
- ⚠️ **既有 `backend/routers/risk.py` 已有 6 个 `/api/risk/*` 端点**（dashboard/oneday/list/seats/stock/{code}/bomb-alerts/seal-snapshots）——合并/去重或命名空间隔离（#7，spec 审查 high）
- `app.py` 注册：现有 37 个 `include_router`（#9 修正）+ `journal` + `drift`
- **测试**：端点契约（请求体/响应）+ 与既有 risk.py 不冲突
- 依赖：P3-T4

### P3-T6 前端 /journal 页面
- React 19 路由 `/journal`
- 与既有 `/portfolio` 区分（持仓 vs 交易日志）
- **测试**：playwright（large 级要求）—— add→update→delete 全流程
- 依赖：P3-T5

### P3-T7 盖章字段清单
- Phase 2 哪些情绪指标写入 journal 记录的 `market` 字段：**STIPhase phase 枚举 + money_effect 中位数**（cycle_position 不进盖章，#双源规则）
- spec Phase 3 工作项 7 原占位符"工作项未跟上"——本任务补上
- 依赖：P2-T1 + P3-T3
- 验收：**Phase 3 G 门**——闭包扫描边界测试全绿（denylist 显式 journal/journal_risk/portfolio）+ 运行时工具遍历全绿 + CRUD + 在险资金 golden values + **盖章零网络（monkeypatch em_get）** + 前端页面（playwright）

---

## 4. Phase 1 — 归档+漂移（视 P2 需求）

### P1-T0 去留判据（YAGNI）
- Phase 2 定稿后：若历史对比需求能由 `sti_timeline` / `weather_history` / 既有快照满足 → **关闭 Phase 1**（task.md 记理由）
- 否则触发 P1-T1

### P1-T1（若做）port archive.py + drift.py
- `archive.py` `capture_day()` 只消费当日已落盘缓存（定时任务排主管线之后）
  - `_fetch_prev_pool` 改走 `astock.em_zt_topic_pool("getYesterdayZTPool")` + `em_get` 限流（audit §4.2 路径 1）
  - `pools` 路径改读 `astock.em_zt_topic_pool` 缓存（audit §4.2 路径 2）
  - `theme_tree` 第三依赖（archive.py:222 `tt.reasons_of`）——audit 审查 #6 旁系，需处理（theme_tree 已丢弃，reasons_of 缓存未命中落入 theme_tree 路径需改写）
- `drift.py` `_day_structure()` 改读 Vibe-Research 基建（同上路径修正）
- 路由 `routers/drift.py`（archive 1 + drift 3 端点，audit §3）
- **测试**：monkeypatch 断言 archive/drift 运行一次只落 `archive/`/`drift/` 子目录，不碰 `first_board_scores_*.json` / `portfolio.json`
- 依赖：P2-T2（确认 P2 历史对比需求）
- 验收：**Phase 1 G 门**（若做）——归档不删除 + 漂移三类分开 + monkeypatch 测试 + 不影响定时管线

---

## 5. 全局约束

- **版本锁定**：`git clone vibe-astock@3c3b7c8` 到 `/tmp/vibe-astock`（不入仓），移植文件头注 SHA
- **数据路径**：所有新路径经 `vr_paths.resolve_data_dir()`，禁硬编码 `~/.vibe-research/`
- **测试隔离**：`VR_DATA_DIR`（conftest.py:14 已有机制）
- **Apache-2.0 署名**：移植文件头 `# derived from vibe-astock@3c3b7c8 (github.com/lzw9560), Apache-2.0, modified` + `# Original author: Simon Lin`
- **合规**（弱合规，工程底线）：不臆造（推算值带口径说明）/ 私有数据隔离（journal/journal_risk 不进 AI）/ em_get 防封（不裸调 requests/akshare）
- **回滚**：每 Phase feature 分支，失败废弃分支；Phase 4 试金石失败→重新评估吸收机制；Phase 3 隐私边界测试不过→不合并

---

## 6. 推荐执行顺序（task 序列）

```
P4-T1 → P4-T2 → P4-T3 → P4-T4  (Phase 4 试金石，可立即开始)
        ↓ (S133 ✅)
P2-T1 → P2-T2 → P2-T3 → P2-T4  (Phase 2，T2 字段映射是卡点)
        ↓
P3-T1 (红灯) → P3-T2 (critical #1 磁盘层) → P3-T3 → P3-T4 → P3-T5 → P3-T6 → P3-T7  (Phase 3 最重)
        ↓
P1-T0 (判据) → P1-T1 (若做)
```

**首个可执行任务**：P4-T1（移植 vibe_astock_util.py，8 函数单测先行）。
