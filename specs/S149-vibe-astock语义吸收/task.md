# S149 原子 task 清单

> 来自 plan.md 拆分。每 task 单一动作，可独立 commit/验证。
> 规模：S=small（免 spec/分支，直接做）/ M=medium（issue 层单轮 review）
> 全局：移植文件头注 `# derived from vibe-astock@3c3b7c8, Apache-2.0, modified`；数据路径经 `vr_paths.resolve_data_dir()`；测试隔离 `VR_DATA_DIR`。

---

## Phase 4 — PromptPack 试点（试金石，可立即开始）

### P4-T1a 移植 util.py 4 函数 [S]
- `atomic_write_json` / `china_now` / `china_today` / `validate_trade_date`（safe_join 不移植 YAGNI）
- → `backend/utils/vibe_astock_util.py`
- 依赖：无
- 验收：4 函数存在 + 署名头

### P4-T1b 移植 trade_calendar 4 函数 [S]
- `is_settled` / `trade_dates_ending_at` / `live_quotes_are_close_of` / `quote_trade_day`（基于 `vr_paths.is_trading_day`）
- → `backend/utils/vibe_astock_util.py`（同 T1a 文件）
- 依赖：P4-T1a
- 验收：4 函数 + 基于 is_trading_day

### P4-T1c vibe_astock_util 单测 [S]
- `backend/tests/test_vibe_astock_util.py`——8 函数单测（含 is_settled 边界：盘前/盘中/盘后/非交易日）
- 依赖：P4-T1b
- 验收：8 函数单测全绿

### P4-T2a 移植 PromptPack dataclass + RESEARCH_PACK [S]
- 砍 focus_model/focus_skeleton/render_focus 三件套
- → `backend/prompt_pack.py`
- 依赖：无
- 验收：PromptPack + RESEARCH_PACK（纯文本字段）

### P4-T2b PromptPack 单测 [S]
- `test_prompt_pack.py`——默认包加载 + 字段
- 依赖：P4-T2a
- 验收：加载 + 字段全绿

### P4-T3a chat.py PromptPack 接口 + analyst_style hook [S]
- SYSTEM_PROMPT 之上加 PromptPack 接口；analyst_style→`{ANALYSIS_FRAMEWORK}` hook（chat.py:36/70）
- 依赖：P4-T2a
- 验收：PromptPack 注入 SYSTEM_PROMPT

### P4-T3b analyst_len / chat_guidance 接线 [S]
- analyst_len→篇幅约束段 / chat_guidance→个股约束段
- 依赖：P4-T3a
- 验收：两字段生效

### P4-T3c chat PromptPack 不回归测试 [M]
- `test_chat_promptpack.py`——默认包 + 替换 + 回落 + **chat 原行为不回归**（记录 pytest 基线，启动后不低于）
- 依赖：P4-T3b + P4-T4b
- 验收：不回归（基线通过数 ≥ 启动前）

### P4-T4a 本地包 importlib 加载 [S]
- `resolve_data_dir()/prompts_local.py`（经 vr_paths）importlib 加载
- 依赖：P4-T3a
- 验收：本地包能加载

### P4-T4b 损坏/缺失回落 + 日志 [S]
- 缺失/损坏→静默回落默认包 + 记日志
- 依赖：P4-T4a
- 验收：回落场景 + 日志

### P4-G Phase 4 G 门 [S]
- 默认包加载 + 本地包替换 + 回落 + pytest 全绿（不低于启动前基线）
- 依赖：P4-T4b + P4-T3c
- 验收：G 门全过

---

## Phase 2 — 情绪指标扩展（S133 ✅ 可启动）

### P2-T1a 移植 money_effect [S]
- 中位数/翻红率/再涨停率 → `backend/emotion_metrics_ext.py`
- 依赖：P4-T1c（vibe_astock_util）
- 验收：money_effect 输出带口径说明

### P2-T1b 移植 consec_premium（分层）[M]
- 聚合口径（均值/中位）进 `_emotion`；按股明细走独立路由 + 标个股名 + 不进 AI context
- 依赖：P2-T1a
- 验收：分层 + 守 market.py:166 零个股名契约

### P2-T1c 移植 cycle_position（双源规则）[S]
- 作 STIPhase 展示层补充；不进 AI context/journal 盖章
- 依赖：P2-T1a
- 验收：双源规则（不进 AI/journal）

### P2-T1d 移植 build_metrics/render_metrics/day_summary [S]
- 聚合入口 + 文本渲染 + 原始读数
- 依赖：P2-T1a
- 验收：3 函数

### P2-T1e emotion_metrics_ext 单测 [S]
- `test_emotion_metrics_ext.py`——各函数 + 口径说明 + cycle_position 不冲突 STIPhase
- 依赖：P2-T1d
- 验收：单测全绿

### P2-T2a batch_pct 改 fetch_raw [S]
- 内联 urllib qt.gtimg.cn（emotion_metrics.py:7,29-55）→ `data/sources/tencent.py::fetch_raw`，提取 change_pct
- 依赖：P2-T1a
- 验收：不裸调 urllib

### P2-T2b fetch_prev_pool→em_zt_topic_pool + 字段映射表 [M]
- **先列映射表**（ret/prev_boards/limit_price/close → em_zt_topic_pool 字段）→ 实现 `_settled_pool`（:165）改写
- 依赖：P2-T1a
- 验收：映射表 + 改写 + 不裸调

### P2-T2c is_limit_up→字段判定 [S]
- 基于映射后字段机械判定（close ≈ limit_price，定容差阈值）
- 依赖：P2-T2b
- 验收：判定 + 容差阈值定义

### P2-T2d from .fetchers/.data→eastmoney/astock [S]
- import 语句改写（工作项 4/5）
- 依赖：P2-T2b
- 验收：import 指向 Vibe-Research 基建

### P2-T2e import 改写端到端测试 [M]
- 字段映射单测 + money_effect/consec_premium 真实取数
- 依赖：P2-T2d
- 验收：端到端全绿

### P2-T3a 确认前端挂载页面 [S]
- 读 frontend/src 确认 Sentiment Weather 页/Market 页存在
- 依赖：P2-T1d
- 验收：挂载点确认

### P2-T3b 前端组件 + cycle_position 双源标注 [M]
- 新指标挂既有页面；cycle_position 标注口径差异（STIPhase=主）
- 依赖：P2-T3a
- 验收：双源标注 + vitest 绿

### P2-T4a 确认是否读 lianban_stocks 字段 [S]
- 若新指标读 price/pct/amount → 触发 P2-T4b
- 依赖：P2-T1b
- 验收：确认结果

### P2-T4b S130 修复并入（条件）[S]
- price/pct/amount 零值归一 None（S130）
- 依赖：P2-T4a（确认需要）
- 验收：S130 修复生效

### P2-G Phase 2 G 门 [S]
- 新指标带口径说明 + 不与 STIPhase 冲突 + pytest 全绿（不低于启动前基线）
- 依赖：P2-T3b + P2-T2e
- 验收：G 门全过

---

## Phase 3 — 交易日志（最重，隐私边界先行）

### P3-T1a 闭包扫描测试红灯 [M]
- `test_journal_privacy.py`——从 chat.py 出发传递 import 图（含 ai/tools 全注册模块），denylist 显式 `journal`/`journal_risk`/`portfolio`（不靠子串匹配）
- 依赖：无
- 验收：红灯（实现前失败）

### P3-T1b 运行时工具遍历测试 [S]
- `registry.execute()` 遍历所有注册工具，断言返回值不含个人数据字段
- 依赖：P3-T1a
- 验收：红灯

### P3-T1c ast.walk 惰性导入覆盖 [S]
- 函数内惰性 import 用 ast.walk 覆盖
- 依赖：P3-T1a
- 验收：惰性导入被扫到

### P3-T2a precompute_daily 落盘 JSON [M]（critical #1）
- 落盘 `<VR_DATA_DIR>/daily-review/<date>.json`（经 vr_paths）
- 依赖：P3-T1a（红灯先行）
- 验收：JSON 落盘

### P3-T2b get_daily_review 先读磁盘 fallback [M]（critical #1）
- 先读磁盘 → fallback `generate_review`（原网络路径）
- 依赖：P3-T2a
- 验收：先读磁盘

### P3-T2c _market_context 走磁盘层 [S]
- 走 P3-T2b 磁盘层，零网络盖章
- 依赖：P3-T2b
- 验收：零网络

### P3-T2d 盖章零网络测试 [M]
- monkeypatch `em_get` 断言 `_market_context` 未触网 + 磁盘读写 + fallback 路径
- 依赖：P3-T2c
- 验收：monkeypatch em_get 未调用

### P3-T3a port journal.py 骨架（CRUD + Lock）[M]
- `backend/journal.py`——CRUD + `threading.Lock`（防静默丢单 journal.py:125）
- 依赖：P3-T2c
- 验收：CRUD + 锁

### P3-T3b _market_context 接磁盘层 [S]
- 走 P3-T2c
- 依赖：P3-T3a
- 验收：接磁盘层

### P3-T3c _stock_context→em_zt_topic_pool [S]
- 从 market_facts.pools 改读 astock.em_zt_topic_pool
- 依赖：P3-T3a
- 验收：接 em_zt_topic_pool

### P3-T3d vr_paths 数据目录 [S]
- 数据目录经 `vr_paths.resolve_data_dir()`
- 依赖：P3-T3a
- 验收：不硬编码 home

### P3-T3e fills/fee 计算 [M]
- fills 格式 + fee（commission_rate/stamp_tax_rate/transfer_fee_rate）计算口径
- 依赖：P3-T3a
- 验收：fee 计算正确（golden values）

### P3-T3f journal.py 单测 [M]
- CRUD + 锁 + fills/fee
- 依赖：P3-T3e
- 验收：单测全绿

### P3-T4a port at_risk + excursion→journal_risk [M]
- → `backend/journal_risk.py`
- 依赖：P3-T3a
- 验收：两模块合入

### P3-T4b port attribution + inbox [S]
- 合入 journal_risk.py
- 依赖：P3-T4a
- 验收：两模块合入

### P3-T4c port risk（风险宪法）[M]
- 合入 journal_risk.py
- 依赖：P3-T4b
- 验收：risk 合入

### P3-T4d journal_risk 行数检查 + 拆分 [M]
- 5合1=65KB≈1625 行，超 800 行上限→拆 2-3 模块
- 依赖：P3-T4c
- 验收：每模块 ≤800 行 或 拆分理由

### P3-T4e journal_risk 隐私约束 [S]
- import 图不得出现 chat/ai/tools（#4）；闭包扫描 denylist 含 journal_risk
- 依赖：P3-T4d
- 验收：闭包扫描绿（P3-T1a 转绿）

### P3-T4f journal_risk 单测 [M]
- 在险资金 golden values（从 test_core_logic.py 提取）+ MFE/MAE + 归因 + inbox
- 依赖：P3-T4e
- 验收：单测全绿

### P3-T5a routers/journal.py（journal 7 端点）[M]
- journal 7 端点（audit §3 契约）
- 依赖：P3-T3f
- 验收：7 端点契约

### P3-T5b risk 9 端点 + 既有 risk.py 合并 [M]
- risk 9 端点；与既有 `backend/routers/risk.py` 6 端点合并/去重或命名空间隔离（#7）
- 依赖：P3-T4f
- 验收：不冲突

### P3-T5c app.py 注册 [S]
- 37 include_router + journal + drift（#9 修正）
- 依赖：P3-T5a + P3-T5b
- 验收：注册成功

### P3-T5d 路由端点测试 [M]
- 端点契约（请求体/响应）+ 与既有 risk.py 不冲突
- 依赖：P3-T5c
- 验收：端点全绿

### P3-T6a React /journal 路由 + 页面 [M]
- 路由 /journal；与 /portfolio 区分
- 依赖：P3-T5d
- 验收：页面可加载

### P3-T6b playwright e2e [M]
- add→update→delete 全流程
- 依赖：P3-T6a
- 验收：e2e 全绿

### P3-T7a 盖章字段定义 [S]
- journal market 字段：STIPhase phase + money_effect 中位数（cycle_position 不进）
- 依赖：P2-T1d + P3-T3a
- 验收：字段定义

### P3-T7b 盖章字段测试 [S]
- 盖章字段写入 + cycle_position 不在
- 依赖：P3-T7a + P3-T3f
- 验收：测试绿

### P3-G Phase 3 G 门 [S]
- 闭包扫描全绿（denylist 显式 journal/journal_risk/portfolio）+ 运行时遍历全绿 + CRUD + 在险资金 golden + 盖章零网络（monkeypatch em_get）+ 前端（playwright）
- 依赖：P3-T7b + P3-T6b + P3-T4f + P3-T2d
- 验收：G 门全过

---

## Phase 1 — 归档+漂移（视 P2 需求）

### P1-T0 去留判据 [S]
- P2 定稿后：历史对比能否由 sti_timeline/weather_history/既有快照满足→满足则关闭 Phase 1（记理由）
- 依赖：P2-G
- 验收：判据决策

### P1-T1a archive.py capture_day 改走 em_get+缓存 [M]（条件）
- `_fetch_prev_pool`→em_zt_topic_pool+em_get；pools 路径→astock 缓存
- 依赖：P1-T0（触发）
- 验收：不裸调 akshare

### P1-T1b theme_tree 第三依赖处理 [S]
- archive.py:222 `tt.reasons_of` 缓存未命中落入 theme_tree——改写
- 依赖：P1-T1a
- 验收：theme_tree 路径改写

### P1-T1c drift.py _day_structure 改写 [M]
- 从 archive.get+market_facts.pools 改读 Vibe-Research 基建
- 依赖：P1-T1a
- 验收：改读基建

### P1-T1d routers/drift.py [M]
- archive 1 + drift 3 端点（audit §3）
- 依赖：P1-T1c
- 验收：4 端点契约

### P1-T1e archive/drift 隔离测试 [M]
- monkeypatch 断言只落 archive/drift 子目录，不碰 first_board_scores/portfolio.json
- 依赖：P1-T1d
- 验收：隔离测试绿

### P1-G Phase 1 G 门 [S]（若做）
- 归档不删除 + 漂移三类分开 + monkeypatch + 不影响定时管线
- 依赖：P1-T1e
- 验收：G 门全过

---

## 执行序列

```
P4-T1a→T1b→T1c → P4-T2a→T2b → P4-T3a→T3b → P4-T4a→T4b → P4-T3c → P4-G
                ↓
P2-T1a→T1b→T1c→T1d→T1e → P2-T2a→T2b→T2c→T2d→T2e → P2-T3a→T3b → P2-T4a(→T4b) → P2-G
                ↓
P3-T1a→T1b→T1c → P3-T2a→T2b→T2c→T2d → P3-T3a→T3b→T3c→T3d→T3e→T3f → P3-T4a→T4b→T4c→T4d→T4e→T4f → P3-T5a→T5b→T5c→T5d → P3-T6a→T6b → P3-T7a→T7b → P3-G
                ↓
P1-T0 →（若触发）P1-T1a→T1b→T1c→T1d→T1e → P1-G
```

**首个可执行 task**：P4-T1a（移植 util.py 4 函数）。
