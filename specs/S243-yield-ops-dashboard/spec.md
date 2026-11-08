# S243 · 运维 Yield 看板（打新/CB/逆回购）

> **状态**：spec 草案（2026-11-08）
> **来源**：专家审查 synthesis P0（[[expert-review-2026-11-08]]）+ 用户决策 GO 全实施

## 1. 问题/目标

选股因子 alpha 已 definitive 穷尽（5/5 closure + 300+ 历史 + 外部学术印证，见 [[zuojianfa-finalized-2026-11-08]]）。practitioner reframe：散户真 edge 在 sizing/风控/行为纪律/结构性 underpricing，**不在选股**。

本项目零运维 yield 模块。散户全可达的结构性 yield（非选股 alpha）：
- **逆回购 GC001**：底仓闲置资金尾盘 sweep，零风险 2-3%/年，季末/年末飙升 5-15%。无门槛。
- **可转债信用申购**：零成本（信用申购无市值要求），AA+ 首日均 +18.7%。中签率低但零成本 lottery。
- **打新**：底仓红利低波已满足市值，2024 首日均 +252% 破发率 2%。BUT 注册制后破发率升，须筛选。

**目标**：看板加运维 yield panel + scheduler 提醒，吃结构性 yield。非自动交易（PaperPortfolio 无 broker），是提醒+规则辅助用户手动执行。

## 2. 需求清单

### Phase 1: 逆回购 sweep 提醒（最简，立即生效，零风险）
- R1.1 router `/api/yield/repo`：返回 GC001(sh204001) 实时年化利率 + 当日是否季末/年末标记
- R1.2 scheduler cron 14:30（交易日）：GC001 >3% OR 季末/年末 → 飞书提醒"逆回购 sweep 时机"
- R1.3 前端 YieldPanel：显示 GC001 实时 + 季末/年末标记 + 历史利率走势

### Phase 2: CB 信用申购日历
- R2.1 router `/api/yield/cb`：bond_zh_cov() 返回 CB 列表 + 申购日/上市日
- R2.2 scheduler 09:15 cron：当日有 CB 申购 → 飞书提醒（信用申购 9:30-15:00）
- R2.3 前端 YieldPanel：CB 申购日历

### Phase 3: 打新筛选红线（deferred——数据源待调研）
- R3.1 IPO 申购日历数据源调研（akshare 无现成 API，须东财新股日历/cctv/其他）—— deferred
- R3.2 打新筛选规则：剔高发行 PE / 低 ROE / 高负债 / ST / 周期顶行业（避雷降破发损失，非选 alpha）
- R3.3 scheduler 09:15 cron：当日有新股申购 → 飞书提醒 + 筛选红线结果

## 3. 受影响文件

- `backend/routers/yield.py`（新）—— /api/yield/repo + /api/yield/cb
- `backend/scheduler/seed.py`—— 加 yield_repo_remind（14:30）+ yield_cb_remind（09:15）cron task
- `backend/scheduler/executors/yield_ops.py`（新）—— repo_remind + cb_remind executor
- `frontend/src/components/YieldPanel.tsx`（新）—— GC001 + CB + 打新 panel
- `backend/ai/tools/`（chat.TOOLS 加 query_yield）—— AI 助手可查 yield
- `backend/data/sources/akshare_yield.py`（新）—— GC001 + CB 数据获取封装

## 4. 验收标准

- AC1: `/api/yield/repo` 返回 GC001 实时利率 + 季末/年末标记
- AC2: 14:30 cron 在 GC001>3% 或季末/年末时发飞书提醒（平日 GC001<3% 不打扰）
- AC3: `/api/yield/cb` 返回当日申购 CB 列表
- AC4: 09:15 cron 当日有 CB 申购时发飞书提醒
- AC5: 前端 YieldPanel 显示三块（GC001/CB/打新 placeholder）
- AC6: chat.TOOLS 加 query_yield，AI 助手可查当日 yield 时机
- AC7: pytest yield_ops executor + router 测试通过
- AC8: 飞书提醒不轰炸（最多 2 条/日：09:15 CB + 14:30 逆回购，仅触发条件时）

## 5. 合规自查（弱合规，私人助理定位）

工程底线（必过）：
- ✅ 判断须可复现：GC001 利率/CB 申购日来自 akshare 公开数据，可复算
- ✅ 私有数据隔离：yield 数据公开，无持仓/API key 涉及
- ✅ 防封：akshare 走 em_get 限流（akshare bond_zh_hs_cov_min / bond_zh_cov 是东财 datacenter 非 push2his，低封禁风险；仍加 cache_response ttl + 熔断器）

仪式类（风险提醒级）：
- 打新筛选规则是"避雷"非"选 alpha"——降低破发损失，不给"必中"承诺
- CB 申购提醒是"零成本 lottery"——中签率低，不夸大收益
- 逆回购是"现金管理 yield"——非超额收益

## 6. 备注

- Phase 3 打新筛选 deferred 因 IPO 申购日历数据源不确定（akshare 无现成 API）。先实施 Phase 1+2（数据源确定），Phase 3 数据源调研后补
- 非自动交易（PaperPortfolio 无 broker/xtquant/qmt）——提醒+规则辅助用户手动执行，反而 sound（用户最终决策）
- 与 combo paper tracking settle（60 天 ~11 月底）并行，互不影响
