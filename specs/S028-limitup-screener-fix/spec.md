# Spec: S028 — limitup_screener 文案/触发/R3名/条件展示 修复

> 状态：已实现(2026-08-06)
> 作者：Claude  日期：2026-08-06
> 关联：S023（漏斗可用性与因子解耦）、S024（拓扑展示）、S026（pre-market-async）
> 级别：medium（跨层、>50 行；不碰外部数据源，#3 自动 seed 另开 large spec）
>
> 验收：A1-A3/A5/A6 经 `tests/test_s028_limitup_fixes.py`（9 用例）+ 全量 `pytest -m "not live"`（778 passed, 0 failed）通过；A4 前端 tsc 通过，待用户手验。改动 commit 于 develop。

## 1. 问题 / 目标

候选池漏斗 + 盘前简报里"涨停基因选股"因子在 0 候选时文案误导（"预计算可能未执行"实为"0 合格"）、手动触发端点 500、漏斗 R3 层 name 退化成 code、且因子层不展示筛选条件——用户看不清系统在干什么。本次修这 4 项正确性 / 可观测性缺陷，让用户能在 0 候选时看清"扫了多少、为何 0、用了什么标准"。

## 2. 背景

- **涨停基因因子**：`backend/factors/limitup_screener_factor.py` 包装 `PreMarketWorkflow`（`pre_market_workflow.py`），输出单层 `FunnelLayer`（layer_id="LS"）。
- **数据流**：`limitup_screener.service.get_screener_result(date)` → 命中缓存/DB 或 90s 超时懒算 → `ScreenerResult{gene_scores, qualified, high_gene}` → `PreMarketWorkflow.run()` 把 `qualified`→`report.candidates`、`high_gene`→`report.strong_candidates`、未达标股→`report.filtered_out`、screener 异常→`report.warnings`。
- **基因得分实为五维加权**（`limitup_screener/models.py:133-143` calc_total_score）：次日溢价率 25% + 红盘率 25% + 封板率 25% + 炸板后溢价 15% + 涨停频次 10%；阈值 `GENE_QUALIFY_THRESHOLD=60`、`GENE_HIGH_THRESHOLD=75`（`models.py:27-28`）。FACTOR_NAME 文案"八项标准"为历史遗留，本次不改正文（避免破坏前端引用），但在 conditions 里如实列五维。
- **漏斗 R3**：`backend/candidate_funnel/funnel.py:161` R3 `passed` 的 name 仅取 `auction`/`catalyst`，二者对无竞价/催化数据的票不带头名 → 回退成 code（实测 R3 大量 `{"code":"603106","name":"603106"}`，R1/R2 正常）。
- **文案现状**：`limitup_screener_factor.py:97-100` 在 `not candidates` 时恒标 `data_status="未取得"` + reason "预计算可能未执行"（三元里 `"ok"` 分支是死代码——进该块时 `report.candidates`/`strong_candidates` 必空）。无法区分"screener 跑了但 0 合格"与"screener 真没跑/超时"。
- **前端**：`PreMarketBriefing.tsx` 的 `FactorSection` 不渲染 `factor.layers`/conditions；`missing = data_status==="未取得"`（行137）控制 warning 块。0 候选时用户只看到"0 只候选 + 预计算可能未执行"，看不到五维标准/阈值/扫描数。
- **DB 实测**：今天 2026-08-06 入库 79 行涨停股基因得分，最高 58.45，全员 < 60 → qualified=0 → 触发上述误导文案。预计算其实跑了（DB mtime 22:03）。

## 3. 需求清单

- [ ] R1 拆分 `data_status`：screener 成功但 0 合格 → `"无合格标的"`（reason 含扫描数 + 阈值）；screener 异常/超时 → `"未取得"`（保留预计算/超时提示）；非交易日无数据 → `"未取得"`（reason "今日无涨停股数据"）。
- [ ] R2 修 `backend/routers/limitup/screener.py` 的 `POST /api/limitup/screener/trigger`：补 `datetime` 导入，手动触发可用，返回 `200 {status:"started", date}`。
- [ ] R3 修 `backend/candidate_funnel/funnel.py` R3 层 name 回退顺序为 genes→activity→auction→catalyst→code（与 `final_candidates` 行179-184 一致）；`_filter_r3` 行82 同步修。
- [ ] R4 涨停基因因子 `FunnelLayer` 补 `conditions`（五维权重 + 合格阈值 + 高基因阈值 + 战法匹配 + 仓位建议）；`PreMarketBriefing.tsx` 的 `FactorSection` 渲染 conditions，并在 `"无合格标的"` 状态展示扫描数摘要，让用户看清"系统在干什么"。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/factors/limitup_screener_factor.py` | R1 重写 `not candidates` 分支：用 `report.warnings`（异常）+ `report.filtered_out`（有数据 0 合格）区分三态；R4 给 `FunnelLayer` 补 `conditions` 列表；`config_out` 暴露 `scanned_count` |
| `backend/routers/limitup/screener.py` | R2 顶部加 `from datetime import datetime`（trigger 端点 :54 用到） |
| `backend/candidate_funnel/funnel.py` | R3 修 `_filter_r3`（:82）name 回退 + R3 `passed`（:161）name 回退，补 genes/activity 来源 |
| `frontend/src/pages/workflow/PreMarketBriefing.tsx` | R4 `FactorSection` 渲染 `factor.layers[0]?.conditions`；新增 `"无合格标的"` 分支（非 warning、显示扫描数摘要）；`missing` 判定维持 `"未取得"` |

## 5. 设计方案

### R1 三态判定（不改 PreMarketReport 结构）

`report` 已带足够信号，无需加字段：

```
if not candidates:
    if report.warnings:                       # run() :118-121 screener 抛异常/超时
        data_status = "未取得"
        reason = "涨停基因选股数据未取得（预计算可能未执行或超时）"
    elif report.filtered_out:                # _build_candidate_pool :177 有数据但 0 合格
        scanned = len(report.filtered_out) + len(report.candidates) + len(report.strong_candidates)
        data_status = "无合格标的"
        reason = f"今日扫描 {scanned} 只涨停股，均未达合格阈值 {GENE_QUALIFY_THRESHOLD} 分"
    else:                                    # screener 成功但 gene_scores 空（非交易日/无涨停）
        data_status = "未取得"
        reason = "今日无涨停股数据"
    config_out["data_status"] = data_status
    config_out["reason"] = reason
    config_out["scanned_count"] = scanned (only when 无合格标的)
```

- `scanned` 公式成立依据：`_build_candidate_pool` 把 `gene_scores` 中非 qualified/high 的全塞 `filtered_out`，故 `len(filtered_out)+candidates+strong_candidates == len(gene_scores)`。
- 不展示"最高 X 分"：`report` 不带各股分数，避免为单条文案加字段/二次查询（YAGNI）。用户可点 `/api/limitup/screener?date=` 看明细。

### R2 datetime 导入

最小修：`from datetime import datetime` 加到文件顶部 import 区。trigger 端点 :54 `datetime.now().strftime("%Y-%m-%d")` 即可用。不改用交易日（trigger 是手动"跑今天"，today 即可；盘后调度在 #3 另 spec 处理）。

### R3 name 回退

`_filter_r3` 与 R3 `passed` 统一用回退链：`genes.get(c,{}).get("name") or activity.get(c,{}).get("name") or auction.get(c,{}).get("name") or catalyst.get(c,{}).get("name") or c`。genes/activity 在 R1/R2 已采集且带头名，保证不退化。注意：`_filter_r3` 当前签名只收 `(codes, auction, catalyst)`，需扩参传 `genes`/`activity` 或在调用处预先解析 name——选扩参（显式、可测）。

### R4 conditions 内容

`FunnelLayer.conditions` 列表（涨停基因因子层）：

```
[
  "基因得分=次日溢价率25%+红盘率25%+封板率25%+炸板后溢价15%+涨停频次10%",
  f"合格阈值≥{GENE_QUALIFY_THRESHOLD}",
  f"高基因≥{GENE_HIGH_THRESHOLD}",
  "战法匹配（8大战法自动匹配）",
  "仓位建议",
]
```

阈值从 `limitup_screener.models` 导入常量，不硬编码。前端 `FactorSection` 新增条件 chips 块（复用 `FunnelLayers.tsx:74-83` 样式），在 `data_status==="无合格标的"` 时显示 reason 摘要（info 色，非 warning）。

## 6. 验收标准

- [ ] A1 0 合格场景（今日 79 只全 < 60）：`GET /api/workflow/pre-market` 的 limitup 因子 `data_status==="无合格标的"`、`config.reason` 含"扫描 79 只"与"60 分"，不再出现"预计算可能未执行"。
- [ ] A2 `POST /api/limitup/screener/trigger` 返回 `200 {"status":"started","date":"..."}`（不再 500）。
- [ ] A3 `GET /api/workflow/funnel/layers` 的 R3 层 `passed` 各项 `name` 为中文名（无竞价数据的票也不再 `name===code`）；`filtered_out` 同。
- [ ] A4 盘前简报涨停基因因子卡可见五维 + 阈值 conditions chips；0 候选时可见"扫描 N 只涨停股，均未达阈值 60 分"摘要。
- [ ] A5 `pytest -m "not live"` 全过（含新增/改动测试）。
- [ ] A6 涉及数据的 reason 文案基于 `report` 实际字段，禁臆造（工程底线）。

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机：本次仅修文案/展示/正确性，不新增方向性研判；涨停股 code/name 属公开榜单客观事实，可呈现（CLAUDE.md §1.1）。
- [x] 判断可复现：reason 文案基于 `report.warnings`/`filtered_out`/`candidates` 实际字段 + 阈值常量，可复算，禁臆造/心算（工程底线）。
- [x] 涨停四池/连板股榜个股：公开榜单客观事实，可呈现 code/name。
- [x] 用户私有数据：本次不涉持仓/研报/key；不动 `.vibe-research/`。
- [x] 东财端点：本次不新增/修改 em_get 调用（trigger 端点调既有 `precompute_daily_async`，#3 自动 seed 已剔出）。

## 8. 测试计划

- **单元**：`backend/tests/` 新增 `test_limitup_screener_factor_status`：构造 `report` 三态（warnings 非空 / filtered_out 非空 / 全空），断言 `data_status` 与 `reason`；新增 `test_funnel_r3_name_fallback`：auction/catalyst 无 name 时 R3 passed name 取自 genes/activity。
- **端点**：`test_limitup_screener_trigger`：POST trigger 断言 200 + `status=="started"`（mock `precompute_daily_async` 避免真跑）。
- **离线快测**：`cd backend && .venv/bin/python -m pytest -m "not live"`。
- **手动**：`curl -X POST localhost:8900/api/limitup/screener/trigger`；刷新 `/workflow/pre-market` 看涨停基因因子卡文案与 conditions；`/candidates` 页看 R3 name。

## 9. 风险与回滚

- **R1 新 status 影响前端**：`PreMarketBriefing.tsx:137` `missing` 判 `"未取得"`；新 `"无合格标的"` 不会触发 warning 块——R4 同步加新分支展示摘要，否则 0 候选时卡片会空。前后端同 commit。
- **R3 `_filter_r3` 扩参**：调用处仅 `funnel.py:155`，影响面可控；单测覆盖。
- **回滚**：单 commit（medium 直接 develop），`git revert` 即可。

## 10. 剔出本次（另开 spec）

- **#3 自动预计算调度**（启动 seed `limitup_precompute` 定时任务，工作日 15:30 自动跑、调 em_get）：按 AGENTS.md "碰外部数据源"升 large 级，另开 spec（feature 分支 + grill + playwright）。本次 R2 修好手动 trigger 即可满足"手动触发预计算"。
- **#5 gene_scores DB 路径迁移**（`backend/limitup_screener/vibe_research.db` → `.vibe-research/`，符合私有数据隔离约定）：需带数据迁移，有丢历史 8 天数据风险，另开 spec。
