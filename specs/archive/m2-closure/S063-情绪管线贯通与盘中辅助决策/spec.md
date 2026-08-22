# S063 · 情绪管线贯通与盘中辅助决策

> **级别**: large（碰外部数据源采样 + 新数据表 + 工作流头部重写 + 盘中辅助决策三层 + 前端多页改动）
> **分支**: `feature/S063-sentiment-pipeline`
> **日期**: 2026-08-12
> **状态**: 已实现（2026-08-13）— T1-T32 落地，T33 pytest 全过，T34 live 冒烟待交易日

---

## 1. 背景与动机

### 1.1 问题

情绪气象站是 PRD 定义的"控制中枢"（天气→风格切换+熔断），但实际实现是架构孤岛：

- **STI 采集三处独立**：`workflow.py._fetch_market_emotion` 拿 STI 分数但不拿 weather_state；`funnel.py._fetch_sentiment_phase` 拿 weather_state 但只用于阈值自适应；气象站页面独立调全量。三处互不知情。
- **weather_state 不进简报**：盘前简报的 `MarketEmotionBlock` 只有 STI 分数+三率，没有天气状态、熔断状态、战法开关。
- **`calc_weather_fit` 是孤儿函数**：8 个战法都有 `weather_regimes` 字段，但 `match_strategies` 不看天气，`calc_weather_fit` 从未被调用（仅测试）。
- **盘中监控零情绪**：IntradayMonitor 完全没有情绪数据，盘中是最需要看天气的时刻。
- **STI 时间属性混乱**：盘前 `_fetch_market_emotion(T)` 对当天调 `em_zt_topic_pool`，但市场没开必返空；`_fetch_sentiment_phase` 读 DB latest 实际是 T-1 数据但不标注来源日期。
- **STI 无盘后定时计算**：`refresh_weather()` 只重读 DB 不触发计算，STI 写入时机不确定。

### 1.2 目标

1. 情绪数据一次采集、管线头部持有、逐级下传——不再三处独立调
2. T-1 情绪作为次日硬标准：盘前读 T-1 STI/weather → 战法开关 → 阈值 → 仓位限制
3. 盘中辅助决策四层：分数+色带、持仓×情绪联动、条件场景推演、T+1 预判
4. 路由归口：`/sentiment/weather` 收编为 `/workflow` 二级页面

---

## 2. 架构设计

### 2.1 时间线

```
Day T-1 盘后（15:30）
  定时任务 → engine.compute(T-1 收盘数据) → save_result → DB
  → SentimentContext {source_date: T-1, weather_state, sti_score, fuse_state, allowed_styles}

Day T 盘前（08:00）
  读 T-1 SentimentContext（不实时计算）
  → 显式标注"昨日情绪 · T-1 晴天"
  → weather_state → 战法开关头部（允许/禁用风格）
  → weather_state → resolve_thresholds（补 source_date 标注）
  → weather_state → PositionAdvisor（暴风雨 → 仓位上限=0）

Day T 盘中（09:30-15:00）
  按黄金窗口频率采样 em_zt_topic_pool
  Layer 1: 4 维度 + 分数 + 趋势箭头 + T-1 基线色带（被动展示）
  Layer 2: 持仓×情绪联动表（主动关联，tencent_quote 拉持仓股报价）
  Layer 3: 条件场景推演 if-then + 历史参照（主动推理）
  Layer 4: T+1 预判双场景（14:30 专项，STI 公式确定性推算）

Day T 盘后（15:30）
  计算当日 STI → 持久化 → 成为 T+1 硬标准
  回填 T+1 预判的 actual_score（投影校准）
```

### 2.2 SentimentContext 数据结构

```python
@dataclass
class SentimentContext:
    source_date: str           # T-1 日期（数据来源日）
    decision_date: str         # T 日期（决策适用日）
    weather_state: str | None  # 晴天/阴天/暴风雨/极端反弹
    sti_score: float | None    # T-1 STI 分数
    sti_phase: str | None      # T-1 STI 阶段
    fuse_state: dict | None    # 三条熔断规则状态
    allowed_styles: list[str]  # 今日允许的战法 code 列表
    forbidden_styles: list[str]# 今日禁用的战法 code 列表
    composite_score: float | None  # 多因子综合分
    factors: dict | None       # 5 因子明细
```

### 2.3 盘中采样频率

| 时段 | 频率 | 原因 |
|---|---|---|
| 09:25-09:45 | 每 5 分钟 | 竞价+开盘，最高信号密度 |
| 09:45-10:30 | 每 15 分钟 | 首波确认 |
| 10:30-11:30 | 每 30 分钟 | 信号衰减 |
| 13:00-14:30 | 每 30 分钟 | 低信号时段 |
| 14:30-15:00 | 每 5 分钟 | 尾盘决策+T+1预判 |

一天约 12-14 个 snapshot。

### 2.4 盘中评分模型

4 维度固定阈值：

| 维度 | 固定阈值 | 权重 |
|---|---|---|
| 涨停家数 | >80=100 / 50-80=60 / <30=20 | 0.4 |
| 封板率 | >70%=100 / 50-70%=60 / <50%=20 | 0.2 |
| 炸板率 | <15%=100 / 15-30%=60 / >30%=20 | 0.2 |
| 涨跌比 | >2=100 / 0.7-2=60 / <0.7=20 | 0.1 |

综合分数 = 加权平均。趋势 = 当前 vs 上一 snapshot（up/flat/down，正负 3 分内为 flat）。

### 2.5 T-1 基线色带

| 色带 | 条件 | 含义 |
|---|---|---|
| 绿色 | 偏离 T-1 基线 <=5 分 | 与昨日情绪一致 |
| 黄色 | 偏离 5-15 分 | 开始走偏，提高警觉 |
| 红色 | 偏离 >15 分 | 显著背离，人工评估 |

不弹告警、不推送。用户看色带颜色自行判断。

---

## 3. 盘中辅助决策四层

### 3.1 Layer 1: 分数+色带（被动展示）

盘中折线图：x 轴=时间，y 轴=综合分数。叠加 T-1 基线水平线 + 绿/黄/红三色区间带。4 个维度各自画小趋势线（可折叠）。

### 3.2 Layer 2: 持仓×情绪联动（主动关联）

数据源：`workflow_state_repo`（持仓列表）+ `astock.tencent_quote`（持仓股实时报价）。

个股封板状态判定：实时报价 vs 涨停价，封住=接近涨停价且未开板，炸板回封=盘中触及涨停后打开再封回，炸板未回封=触及涨停后打开未封回。

双重压力行（个股炸板未回封+红色区）置顶高亮。

### 3.3 Layer 3: 条件场景推演（主动推理）

基于当前 snapshot 状态 + 趋势，预铺 if-then 分支。历史参照初期样本为 `sti_intraday` 表已有数据（首日为零，逐日积累），诚实标注样本量，不编准确率。

### 3.4 Layer 4: T+1 预判（14:30 专项）

14:30 触发，用当前 4 维度数据预推算收盘 STI。双场景（维持/反弹）。预判可靠性较高：STI 公式确定，输入数据实时，只差 30 分钟变化。收盘后回填 actual_score 做投影校准。

---

## 4. 后端改动

### 4.1 STI 盘后定时计算

`scheduled_tasks.py` 新增定时任务：交易日 15:30 触发，调 `engine.compute()` + `save_result()`，数据来自当日收盘 `market._emotion(T)` + `market._sentiment(T)`。

### 4.2 SentimentContext 模块

新文件 `backend/sentiment_context.py`：
- `build_context(decision_date: str) -> SentimentContext`：读 `sti_timeline` 取 T-1 STI，调 `_calculate_weather_state` 算天气，调 `calc_weather_fit` 算允许/禁用战法，调熔断端点取 fuse_state。

### 4.3 工作流简报改造

`routers/workflow.py`：
- `_fetch_market_emotion(date)` 改为读 T-1 的 STI timeline 行（不调 `get_market_emotion_raw(T)` 盘前必空）。
- 新增 `sentiment_context` 字段到简报 JSON 响应。
- `_fetch_sentiment_phase` 删除，改从 `SentimentContext` 取。

### 4.4 战法匹配标注适配度

`strategies/strategy_matcher.py`：
- `match()` / `match_batch()` 增加可选参数 `weather_state: str | None`。
- 每个 `StrategySignal` 新增 `weather_fit: str` 字段，调 `calc_weather_fit`。

### 4.5 盘中采集端点

新文件 `backend/routers/intraday_sentiment.py`：
- `GET /api/intraday/sentiment/latest`：返回最新 snapshot。
- `GET /api/intraday/sentiment/timeline`：返回当日全部 snapshots。
- `GET /api/intraday/sentiment/holdings`：返回持仓×情绪联动表。
- `GET /api/intraday/sentiment/scenarios`：返回条件场景推演。
- `GET /api/intraday/sentiment/t1-projection`：返回 T+1 预判（14:30 后可用）。
- `POST /api/intraday/sentiment/snapshot`：手动触发一次采样（调试用）。

后台采样：内存 ring buffer + 定时 asyncio task（仅交易时段运行）。

### 4.6 sti_intraday 表

```sql
CREATE TABLE sti_intraday (
    date        TEXT NOT NULL,
    time        TEXT NOT NULL,
    zt_count    REAL,
    seal_rate   REAL,
    break_rate  REAL,
    ad_ratio    REAL,
    score       REAL,
    trend       TEXT,
    t1_baseline REAL,
    projected_t1_score    REAL,
    projected_t1_weather  TEXT,
    actual_score          REAL,
    PRIMARY KEY (date, time)
);
```

迁移文件 `backend/migrations/sti/20260812-001_create_sti_intraday.sql`。自动清理 >60 交易日。

### 4.7 PositionAdvisor 接 weather_state

`strategies/position_advisor.py`：
- `advise()` 增加可选参数 `weather_state: str | None`。
- 暴风雨 → 仓位上限=0（禁止开仓）。
- 极端反弹 → 仓位上限降至 50%。
- 晴天/阴天 → 正常计算。

---

## 5. 前端改动

### 5.1 设计系统

沿用现有"科技玻璃暖橙"主题。天气状态色系：

| 天气 | 色值 | 用途 |
|---|---|---|
| 晴天 | amber `38 92% 55%` | 暖金色环境 |
| 阴天 | slate `215 16% 42%` | 灰蓝中性 |
| 暴风雨 | red `0 74% 60%` | 警示红 |
| 极端反弹 | violet `265 85% 65%` | 紫色反差 |

色带色：绿 `145 62% 47%` / 黄 `38 92% 55%` / 红 `0 74% 60%`。

### 5.2 盘前简报：天气决策条（WeatherDecisionBar）

`PreMarketBriefing.tsx` 顶部新增全宽条（非卡片），纵向流第一块：

- 天气图标 + 天气名 + STI 分数 + 阶段
- 允许/禁用战法 chips（允许=primary 色，禁用=muted 标灰删除线）
- 熔断状态三灯（绿=正常，红=触发）
- 右侧 STI 趋势迷你折线（30 日）
- 背景色微染天气色（极淡的 amber/slate/red/violet tint）

### 5.3 盘中监控：四层辅助决策

`IntradayMonitor.tsx` 重写，纵向四层：

- Layer 1 情绪走势图：ECharts 折线+面积图，T-1 基线虚线+三色区间带+当前点高亮+趋势箭头，4 维度小折线可折叠
- Layer 2 持仓×情绪联动：紧凑表格，双重压力行置顶高亮
- Layer 3 条件场景推演：两栏并列 if-then 卡片，历史参照标注样本量，14:30 前不显示
- Layer 4 T+1 预判：14:30 后双场景+收盘后校准

### 5.4 路由归口

- `/sentiment/weather` → 301 重定向到 `/workflow/intraday`
- Workflow.tsx 盘中阶段卡链接改为 `/workflow/intraday`
- 保留 `/sentiment/weather/*` 路由作为历史兼容

### 5.5 前端 Query Hooks

`lib/query/intraday.ts`（新建）：5 个 hooks 对应 5 个端点。刷新频率：Layer 1/2 每 5 分钟，Layer 3/4 随 Layer 1 刷新联动。

---

## 6. 验收标准

### 6.1 后端

- [ ] AC1 `SentimentContext` 构造正确：`build_context(T)` 返回 `source_date=T-1` 的完整 context
- [ ] AC2 简报 `/api/workflow/pre-market` 响应含 `sentiment_context` 字段
- [ ] AC3 战法信号含 `weather_fit` 字段（晴天+连板接力=适配，晴天+弱转强=不适配）
- [ ] AC4 PositionAdvisor 暴风雨 → 仓位上限=0；极端反弹 → 50%
- [ ] AC5 盘中采样端点返回 4 维度+分数+趋势+色带区间
- [ ] AC6 `sti_intraday` 表创建+迁移+60 日自动清理
- [ ] AC7 14:30 T+1 预判端点返回双场景，收盘后 actual_score 回填
- [ ] AC8 STI 盘后定时任务在交易日 15:30 触发计算+持久化
- [ ] AC9 历史快照简报读 T-1 context（from_snapshot=true）
- [ ] AC10 `pytest -m "not live"` 全过

### 6.2 前端

- [ ] AC11 PreMarketBriefing 顶部 WeatherDecisionBar 渲染
- [ ] AC12 IntradayMonitor 四层纵向布局渲染
- [ ] AC13 走势图：T-1 基线虚线+三色区间带+当前点高亮+趋势箭头
- [ ] AC14 持仓联动表：双重压力行置顶高亮
- [ ] AC15 场景推演 if-then 两栏，历史参照标注样本量
- [ ] AC16 T+1 预判 14:30 前不显示，14:30 后双场景+收盘后校准
- [ ] AC17 `/sentiment/weather` 301 重定向到 `/workflow/intraday`
- [ ] AC18 tsc 全量零错误
- [ ] AC19 简化 playwright：盘前 WeatherDecisionBar + 盘中四层布局渲染

### 6.3 合规自查

- [ ] CC1 不臆造数据：历史参照样本量不足时标注"样本不足"，不编准确率
- [ ] CC2 盘中预判标注"投影，非最终判定"
- [ ] CC3 em_zt_topic_pool 限流防封：复用 TTL 缓存，采样间隔不低于 5 分钟
- [ ] CC4 私有数据隔离：持仓联动只读 workflow_state_repo，不输出个股推荐

---

## 7. 风险与降级

| 风险 | 降级 |
|---|---|
| em_zt_topic_pool 盘中不可用 | 采样失败标 missing，分数=None，趋势维持上一个有效值 |
| T-1 STI 不存在（首日或 DB 空） | SentimentContext 全 None，WeatherDecisionBar 显示"情绪数据未取得"，阈值降级基数 |
| tencent_quote 持仓报价拉取失败 | 持仓联动表个股封板状态标"数据未取得" |
| sti_intraday 表空（首日） | Layer 3 历史参照标注"样本不足（0 日）" |
| 14:30 预判数据不足 | T+1 预判面板显示"数据不足，无法预判" |

---

## 8. 不做

- 盘中自动切换战法（T-1 硬标准不被动摇，盘中只做辅助）
- 盘中天气标签投影（砍掉，只给分数+趋势+色带）
- 告警推送（不弹窗不推送，用户看色带自行判断）
- 8 维度百分位归一化（盘中历史不足，用固定阈值）
- mootdx 盘中情绪数据源（mootdx 无涨跌停池）
- 盘中 STI 实时持久化到 sti_timeline（盘中只写 sti_intraday）

---

## 9. 关联

- PRD: `docs/limitup-trading-workflow-prd.md` S3 情绪气象站
- S002: 打板工作流重构（情绪自适应三模式）
- S055: 盘中封单时序采集与炸板预警
- S056: 天气熔断三铁律补全
- S058: 战法双层卡片层与天气适配过滤
- S049 B: market_emotion 重写（本 spec 再次重构为 T-1 读取）
- STITimelineChart 组件（S062 后新增）

---

## 10. 补充：审查遗漏项

### 10.1 `_fetch_market_emotion` T-1 数据映射

`sti_timeline` 表存储的是 8 个 `dimension_*` 归一化值，而 `_fetch_market_emotion` 当前返回 `seal_rate`（0-1 比率）、`break_rate`、`promotion_rate`、`ladder`（列表）、`zt_count`、`dt_count`。

改造方案：`_fetch_market_emotion` 读 T-1 行时，从 `dimension_seal_rate`/`dimension_limit_up_count`/`dimension_limit_down_count` 等字段映射为简报需要的格式。`ladder` 无法从 `sti_timeline` 重建（需要原始涨停池明细），降级为 `ladder=[]` + 标注"T-1 连板梯队未持久化"。三率从 `dimension_*` 字段取归一化值（0-100），简报渲染时 `/100` 显示。

### 10.2 app.py 注册

`backend/app.py` 新增 `app.include_router(intraday_sentiment.router)`。import 在文件头部 router import 区按字母序插入。

### 10.3 后台 asyncio task 生命周期

- **启动**：app `@app.on_event("startup")` 注册一个 asyncio task `_intraday_sampler_loop`
- **运行条件**：仅交易日 09:25-15:00 运行；非交易时段 task sleep 60s 空转
- **采样调度**：根据当前时间落在哪个黄金窗口区间，计算距下次采样的 sleep 秒数
- **停止**：app shutdown 时 cancel task
- **容错**：单次采样异常 try/except 不中断 loop，记日志后等下一周期

### 10.4 StrategySignal 模型更新

`limitup_strategy.py` 的 `StrategySignal(BaseModel)` 新增字段：
```python
weather_fit: str = "中性"  # 适配/不适配/中性
```
默认值"中性"保证向后兼容（未传 weather_state 时行为不变）。

### 10.5 前端类型定义

`frontend/src/lib/api/types.ts` 新增类型：
```typescript
interface SentimentContext {
  source_date: string;
  decision_date: string;
  weather_state: '晴天'|'阴天'|'暴风雨'|'极端反弹'|'未知';
  sti_score: number | null;
  sti_phase: string | null;
  fuse_state: FuseState | null;
  allowed_styles: string[];
  forbidden_styles: string[];
  composite_score: number | null;
}

interface IntradaySnapshot {
  time: string;
  zt_count: number;
  seal_rate: number;
  break_rate: number;
  ad_ratio: number;
  score: number;
  trend: 'up'|'flat'|'down';
  zone: 'green'|'yellow'|'red';
  t1_baseline: number;
}
```

### 10.6 前端新增组件（mockup 已有，spec 补入 AC）

- **PipelineProgressBar**：盘前/盘中/盘后页顶部 5 节点进度条（T-1 → Ctx → 盘前 → 盘中 → 盘后），当前阶段脉冲高亮
- **StateMachineDashboard**：盘中页状态机实时看板（6 态计数 + 今日流转记录）
- **BreadcrumbDetail**：详情 overlay 导航系统（面包屑 + 返回按钮），所有因子/候选/战法/持仓/指标/快照可点击跳转

### 10.7 盘后页面（PostMarketReview）改造

spec 前端 section 未覆盖盘后页面。补入：
- 当日 STI 结算条（T vs T-1 天气对比 + 变化值）
- 盘中轨迹回放（14 snapshot 走势图 + 关键拐点标注）
- T+1 预判校准面板（投影 vs 实测 + 偏差 + 校准记录）
- 持仓结算表（含状态流转 hold→settled 列 + 情绪复盘列）
- T+1 准备面板（明日硬标准 + 持仓 T+1 行动）
