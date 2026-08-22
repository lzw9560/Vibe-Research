# S094 实施计划（plan）

> 配套 `spec.md`。流程门 large：feature 分支 `feature/S094-战法分类与双pipeline重构`；完整 grill（8 轮已过 + spec 审查 1 轮）；playwright 验收。
> 依赖：S093 已合并（M4 归档）。

## 阶段划分

### S1 后端战法分类 + score_candidates 分流 + confidence
- `strategies/strategy_funnel_registry.py`：
  - 战法按 funnel_type 归组（7 limitup + 5 market_scan）
  - `score_candidates` 加 `funnel_type` 参数（默认全跑，向后兼容既有调用）+ 按 funnel_type 筛战法
  - `confidence` 派生（=strategy_score/100 normalize）+ signal_strength=int(confidence*100)
- dragon_head 不对涨停股跑（funnel_type 分流自动实现）
- 测试：`test_s094_strategy_classify.py`

### S2 后端双 pipeline + 板块轮动修复 + zt_real 口径
- 新建 `market_scan.py`：
  - 通用因子层（relative_strength/ma_bullish/volume_signal/sector_strength 全市场算一次）
  - K线形态子（kline cache + 形态识别：均线回调/反包/突破平台/突破昨日最高）
  - 板块领涨子（sector/industry 板块内相对强度排名）
- `sector_divergence.py`：`calculate_sector_rotation` 数据源修复（不再返 None）
- `market.py`：`zt_count` 改 `zt_real`（L53 已算，去 ST/退市）
- `routers/workflow.py`：双 pipeline 响应（涨停 candidates + 非涨停 candidates）
- 测试：`test_s094_market_scan.py` + `test_s094_sector_rotation.py`

### S3 前端 UI 双 pipeline 上下分区 + 折叠 + 卡片流转
- `Workflow.tsx`：前瞻双 pipeline 上下分区（涨停上主/非涨停下次）+ 折叠收缩
- `StrategyMatchMatrix.tsx`：涨停/非涨停战法分区
- 卡片按 pipeline 流转顺序（①涨停池②涨停战法③breakout④交叉验证 / ⑤板块领涨⑥K线形态⑦非涨停战法）
- 测试：vitest

### S4 前端 UI bug 修（与 S3 可并行）
- `SectorCyclePanel.tsx`：股票代码 2 次修（重复渲染）
- advisory 摘要组件：摘要截断（不显示全部）
- `P2RiskPanel.tsx`：P2 仓位闸显示
- `VerificationCardBlock.tsx`：验证对 spec 设计
- 测试：vitest

### S5 全量回归 + playwright 验收
- pytest + vitest + tsc + vite build 全绿
- playwright e2e AC1-AC9
- 验收收拢（task 勾选 + spec 状态 + 归档）

## 并行策略

- S1 独立（后端战法分类）
- S2 依赖 S1（score_candidates 分流后建 market_scan）
- S3 依赖 S2（双 pipeline 后端就绪）
- S4 可与 S3 并行（UI bug 独立于双 pipeline）
- S5 最后

建议执行顺序：S1 → S2 → S3+S4 并行 → S5。

## 串行纪律与边界

- 不改数据层（快照/票根/影子收益——复用）
- `score_candidates` 加 funnel_type 参数向后兼容（默认全跑，不破既有调用 workflow/pre_market_workflow 等）
- 不新建通知模块（复用 NotificationService）
- 不新建规则引擎（复用 bomb_alert）
- zt_real 口径改动 market._emotion（影响 STI/market_emotion 快照），要 refresh
- market_scan 模块新建——K线形态用 kline cache（baostock 非东财，不防封），板块领涨用 sector/industry（既有防封）
