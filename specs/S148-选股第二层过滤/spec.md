# Spec: S148 — 选股第二层过滤（板别排除 + ST 摘帽/重组 carve-out）

> 状态：实现中（Phase 1a：R1/R2/R4 done + 23 测试绿）
> 作者：lzw9560  日期：2026-09-03
> 关联：S094（双 pipeline）/ S144（§44 测量地基）/ S084（R1-only）/ grill-decisions.md（创业板"不剔除只分组"旧决定，本 spec 反转）/ S070（first-board 链）

## 1. 问题 / 目标

涨停叉漏斗选股（双 pipeline：涨停叉 ‖ 非涨停叉）当前可交易性过滤不一致：ST 只在涨停叉 candidate_funnel R1 滤一处（`funnel.py:84`），非涨停叉 market_scan 不滤 ST → 同张双 lane 口径不一致；创业板/科创板/北交所 0 路滤（688 过滤层无分类，掉 `first_board_filter:1446` "其他"桶）。用户账户未开通创业板/科创板/北交所权限（硬约束），需在双 pipeline 统一排除不可交易标的，同时保留 ST 摘帽/重组/扭亏 play（不 flat 排除）。停牌 descope（不滤，盘中自行跳过，不影响工作流运行）。

## 2. 背景

- 双 pipeline（S094）：涨停叉（`candidate_funnel.run_funnel` + `score_candidates("limitup")`）‖ 非涨停叉（`market_scan.gather_non_limitup_candidates` + `score_candidates("market_scan")`），`workflow._collect` 装配（`workflow.py:161/222/236`），前端 `PipelineFlow` 双 lane。
- ST 现状：`classify_exclusion`（`_filters.py:19`）全仓仅 `funnel.py:84`（R1）调一次；非涨停叉不滤 ST → 同张双 lane 口径不一致。
- 创业板：`first_board_filter.py:70` `exclude_chinext=False`，`first_board_layer_lift.py:78` 引 `grill-decisions.md`"不剔除只分组"——本 spec 反转（理由=用户没权限=硬约束）。
- 科创板 688：仅 `limitup_screener/models.py:179` 涨跌停价计算认，**过滤层无 board 分类函数**。
- 公告/资讯管道已存在：`catalyst.py`（`astock.announcements` + `_ANN_KEYWORDS` 含"重组"型）+ `news_radar_context.py:195`（摘帽/扭亏扫描）→ ST-play radar 可搭便车，不新铺管道。
- §44：双 lane <2x 无 validated edge（`SelectionStageView.tsx:3` 注释）；过滤为可交易性，不为提升 edge。
- first-board 链：当前分叉（自 fetch zt_pool，输出不在 spine），`select_for_entry` 是 §44 no-edge 对象；决策 (a) 接入涨停叉（吃 R1 输出，9 维描述性 context，`select_for_entry` 仓位不作可操作信号）。

## 3. 需求清单

**Phase 1 — 共享过滤 + radar + 接入（先行）**
- [x] R1 新建 `classify_board(code) → 主板/创业板/科创板/北交所/其他`（共享 board 分类，补 688/北交所空缺）
- [x] R2 新建 `classify_tradability(name, code, radar_set) → (keep, reason, st_play?)`：ST（radar 白名单 carve-out）+ 创业板/科创板/北交所 排除；停牌不在此函数（descope）
- [x] R3 日级 ST-play radar（盘后 scheduled）：done——`run_st_play_radar` orchestrator + `_collect_st_codes`（code_industry 全量 ST，覆盖双 lane）+ `_execute_st_play_radar` scheduled task（cron `30 17 * * 0-4`）+ catalyst `_ANN_KEYWORDS` 摘帽型；16 测试绿。news_radar 摘帽/扭亏 = optional（公告 path 已覆盖检测，YAGNI 不做）
- [x] R4 接入点①：`_filter_r1` 改调 `classify_tradability` + `_load_st_play_radar` 加载器（graceful 空）+ `st_play` 进 R1 passed
- [ ] R5 接入点②：`market_scan.gather_non_limitup_candidates`（或其候选产出处）接 `classify_tradability`（非涨停叉首次滤 ST + board）
- [ ] R8 北交所（8/4 开头）一并排除（推断：用户无 100 万权限，已确认同意）

**Phase 2 — first-board (a) 接入（独立 PR，后行）**
- [x] R6 first-board (a) 接入：基础（`run_first_board_filter(date, pool=None)` 注入参数）+ substance（`attach_first_board_analysis` 把首板 9 维 load_scores 缓存接到 lane final_candidates + DiagnosisCard `first_board_analysis` 字段 + 前端 9 维各分描述性展示 + 复合分标"§44 未 validated 不作物买卖信号"）done；`select_for_entry` 仓位不进 spine（保持）；TDD 绿

**前端**
- [ ] R7 候选卡 `st_play` 标展示（摘帽/重组/扭亏）+ first-board 复合分若显示标"无 validated edge"。**依赖**：`st_play` 现已在 R1 passed（funnel_layers 可读），但 `final_candidates` 诊断卡（WatchlistBoard 用）需透传 st_play 进 `DiagnosisCard` 契约（dataclass+builder+API+前端，独立改动，后行）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/candidate_funnel/sources/_filters.py` | 新增 `classify_board` + `classify_tradability`；`classify_exclusion` 保留（radar 复用） |
| `backend/candidate_funnel/funnel.py` | `_filter_r1`（:79-89）改用 `classify_tradability`；`run_funnel`/`_run_funnel_impl` 透传 radar_set |
| `backend/strategies/market_scan.py` / `non_limitup_funnel.py` | 候选产出接 `classify_tradability`（impl 时 grep 确认具体注入点） |
| `backend/candidate_funnel/sources/catalyst.py` | `_ANN_KEYWORDS` 补摘帽关键词 |
| `backend/strategies/news_radar_context.py` | 摘帽/扭亏扫描接线产出 radar 白名单（impl 时确认 :195 上下文产出形态） |
| `backend/scheduled_tasks.py` | 新增日级 ST-play radar task（盘后） |
| `backend/routers/workflow.py` | `_collect` 加载 radar 白名单传给 `run_funnel` |
| `backend/strategies/first_board_filter.py` | (Phase2) `rank_candidates` 改吃外部候选输入；9 维分描述性 + 标签 |
| `frontend/src/components/candidate/*` | `st_play` 标 + 诚实标签（impl 时确认具体组件 DiagnosisCard/FunnelLayers） |

## 5. 设计方案

**`classify_board(code)` 前缀映射**（全仓首个共享 board 分类，补 688/北交所空缺）：
- `60x`/`00x`（600/601/603/605/000/001/002/003）→ 主板
- `300`/`301` → 创业板
- `688`/`689` → 科创板
- `8`/`4` 开头（83/87/43/92…）→ 北交所
- else → 其他

**`classify_tradability(name, code, radar_set)`**（扩展 `classify_exclusion`，加 board + ST carve-out）：
- name 含 ST/*ST 且 code ∉ radar_set → (排除, "ST/*ST 标的", None)
- name 含 ST/*ST 且 code ∈ radar_set → (保留, None, st_play=radar_set[code])
- board ∈ {创业板, 科创板, 北交所} → (排除, "{board} 不可交易（无权限）", None)
- else → (保留, None, None)
- 停牌：不在此函数（descope；盘中自行跳过）

**ST-play radar（日级盘后）**：扫 ST 股池（从 zt_pool/gene_scores 取 name 含 ST 的 ~150-200 只）→ `astock.announcements`（em_get 限流 + circuit_breaker）公告分类 + `news_radar_context` 摘帽/扭亏 → 白名单 `{code: play_type}` 存 `VR_DATA_DIR/st_play_radar.json`。失败降级空白名单（ST 全 flat 排除，不崩，不阻断主流程）。

**为何不选其他**：
- 不在 R1 之外加执行层 gate（停牌 descope 后无需；过滤全在 R1 建池时，架构干净）
- 不沿用 `classify_exclusion` flat ST（要 carve-out 必须区分摘帽/重组）
- first-board 选 (a) 接入而非 (b) 新开分叉（(b) 违反 §44，select_for_entry 无 edge 不作可操作信号）；非 (c) 维持研究态（用户选 (a)）

## 6. 验收标准

- [ ] A1 涨停叉 lane 候选无 ST，除 radar 白名单 re-include 的摘帽/重组/扭亏（带 `st_play` 标）
- [ ] A2 非涨停叉 lane 候选无 ST + 无创业板/科创板/北交所
- [ ] A3 `classify_board` 单测覆盖 5 类板（主板/创业板/科创板/北交所/其他）
- [ ] A4 `classify_tradability` 单测：ST(非白名单)排除 / ST(白名单)re-include+st_play / 各 board 排除 / 普通
- [ ] A5 radar 白名单日级 scheduled 跑通，产出可复现（基于公开公告）
- [ ] A6 (Phase2) first-board `rank_candidates` 吃 涨停叉 R1 输出，无自 fetch zt_pool
- [ ] A7 first-board 复合分若前端显示，标"无 validated edge"（§44）
- [ ] A8 `pytest -m "not live"` 绿（deselect newsradar/s032/s040 flaky）

## 7. 合规与工程底线自查

- [x] 研判/推荐：本 spec 不出研判，只做可交易性过滤 + 描述性 context；用户可见输出挂轻量风险提醒
- [x] 判断可复现：board 分类（code 前缀）+ radar 白名单（公开公告）可复算，禁臆造/心算
- [x] 涨停四池/连板股榜：本 spec 不改榜单呈现
- [x] 用户私有数据：radar 白名单存 `VR_DATA_DIR`（.vibe-research/），不进 git
- [x] 新增东财端点：radar 扫公告走 `astock.announcements`（em_get 底层限流 + circuit_breaker），不裸调

## 8. 测试计划

- **单元**：`classify_board` 5 板覆盖；`classify_tradability` 4 分支（ST 非白名单/ST 白名单/各 board/普通）；`_filter_r1` 集成（ST/非 ST/board/白名单 re-include）
- **集成**：`market_scan` 候选产出接过滤后无 ST/board；radar 产出白名单
- **回归**：`pytest -m "not live"` 全绿，deselect：
  - `test_fetch_global_intel_wm_import_fails`（newsradar 联网 flaky）
  - `test_s032` refresh_loop flaky
  - `test_s040_backfill::test_run_backtest_async_passes_kline_cache`（kline-cache flaky）
- **pre-existing 失败（非 S148 回归）**：`test_s084_subobjects` 3 项（`first_board_filter:211` fbt str-vs-int + `prev_amount_yi` tencent quote），打 em_get push2his 联网 flaky；`git diff --stat` 确认 S148 未碰 first_board_filter/activity
- **手动**：前端候选卡 `st_play` 标 + first-board 复合分诚实标签可见

## 9. 风险与回滚

- **`classify_tradability` 改 `_filter_r1`**：影响涨停叉候选池组成 → 回滚还原 `classify_exclusion` 调用
- **first-board (a) Phase2** 是最大风险（改 `rank_candidates` 签名 + 拔 zt_pool 自取）→ 独立 PR，Phase 1 先行
- **radar 公告 scan 防封**：走 em_get 限流 + circuit_breaker；失败降级空 radar_set（ST 全 flat 排除，不崩，不阻断主流程）
- **非涨停叉 baostock 缓存未扩容**：`market_scan_scored` 恒空（`_collect:232` 注释），过滤接入不影响（空集过滤仍空）
