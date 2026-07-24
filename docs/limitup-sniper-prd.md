# 投研助手 — Investment Research Assistant

> **PRD V2.0** | 更新日期：2026-07-22  
> **前身**：打板策略模块 V1.6 (PRD)  
> **载体项目**：Vibe-Research 个人 AI 投研看板

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| V1.0-V1.6 | 2026-05 ~ 2026-07 | 打板策略模块：5因子基因选股 + 条件匹配展示 + 集合竞价分析 |
| **V2.0** | **2026-07-22** | **重构为"投研助手"：三维度升级 + DSA优秀实践整合 + 投研看板→助手渐进演进** |
| **V2.0.2** | **2026-07-22** | **Oracle审查BLOCKER修复完成：StrategySignal字段修正 + OneDayRisk动态化 + 性能三层拆分 + 路由重构** |
| **V2.0.3** | **2026-07-23** | **用户审查BLOCKER修复：数据新鲜度/死循环防护 + A股通道滑点补偿 + 结算买入价悖论修正 + 封单额/流通盘双指标 + 竞价指标 + 赦免战法开关** |

---

## BLOCKER修复记录（V2.0.2）

> **审查来源**：Oracle审查（ora-1）  
> **修复日期**：2026-07-22  
> **状态**：已修复，待实施验证

### BLOCKER-1：StrategySignal字段修正

**问题**：§4.11.1 中 `StrategySignal` 数据类缺少关键风控字段，无法完整表达战法的入场/出场逻辑。

**修复方案**：

```python
@dataclass
class StrategySignal:
    """战法信号（修正版）"""
    strategy_name: str          # 战法名称
    strategy_code: str          # 首板挖掘/连板接力/炸板回封/低吸龙头/反包战法/N字反击/平台突破/尾盘偷袭
    
    # 入场逻辑
    entry_price: float          # 建议入场价
    entry_condition: str        # 入场确认条件（如"竞价量>5日平均2倍"）
    entry_type: str             # 入场类型（开盘/竞价/尾盘）
    
    # 风控逻辑
    stop_loss: float            # 止损价
    stop_loss_condition: str    # 止损触发条件（如"跌破入场价-3%"）
    take_profit: float          # 止盈价
    take_profit_condition: str  # 止盈触发条件（如"涨至+8%回落"）
    
    # 持仓管理
    max_hold_days: int          # 最大持仓天数
    exit_condition: str         # 主动离场条件（如"连板高度≥3板"）
    
    # 历史统计
    historical_win_rate: float  # 历史成功率
    historical_avg_return: float # 历史平均收益率
    sample_size: int            # 统计样本量（用于置信度评估）
    
    # 当前信号
    confidence: float           # 当前信号置信度 (0-1)
    risk_reward_ratio: float    # 风险收益比
    conditions: dict            # 战法触发条件详情
    
    # 教育性说明
    reasoning: List[str]        # 推荐理由（教育性表述）
    risk_notes: List[str]       # 风险提示
```

**影响范围**：§4.11.1, §4.11.2, §4.11.3, §4.11.4

---

### BLOCKER-2：OneDayRisk动态化

**问题**：§4.13.1 中 `OneDayRisk` 使用静态 `risk_score` 和 `risk_level`，无法反映实时资金流变化。

**修复方案**：

```python
@dataclass
class OneDayRisk:
    """一日游风险评估（动态版）"""
    stock_code: str
    
    # 动态评分（实时更新）
    risk_score: float              # 风险评分 (0-100)，随资金流动态变化
    risk_level: str                # HIGH/MEDIUM/LOW，基于risk_score动态判定
    score_components: dict         # 各维度得分明细（用于解释）
    
    # 资金流维度（动态）
    capital_flow_signal: float     # 资金流信号 (-1 到 +1)，实时更新
    capital_flow_trend: str        # 流入/流出/震荡，基于时序判断
    big_fund_detected: bool        # 是否检测到大基金
    big_fund_type: str             # 大基金类型 (游资/机构/北向)
    fund_flow_history: List[dict]  # 近5日资金流历史（用于趋势判断）
    
    # 龙虎榜维度（半动态）
    dragon_tiger_risk: float       # 龙虎榜风险评分（T+1更新）
    one_day_seats: List[str]       # 一日游特征席位
    multi_seat_signal: bool        # 多席位同时出现信号
    seat_confidence: float         # 席位识别置信度
    
    # 综合判断
    recommendation: str            # 建议 (关注风险/谨慎参与/可正常参与)
    factors: List[str]             # 风险因素列表
    last_updated: str              # 最后更新时间（用于前端展示时效性）
    
    # 动态阈值
    dynamic_thresholds: dict       # 基于市场环境的动态阈值
```

**动态更新机制**：

```python
async def update_one_day_risk_realtime(code: str) -> OneDayRisk:
    """实时更新一日游风险评分"""
    # 1. 获取最新资金流数据（每分钟更新）
    capital_flow = await get_realtime_capital_flow(code)
    
    # 2. 计算动态风险评分
    base_score = calculate_base_risk(code)
    flow_adjustment = calculate_flow_adjustment(capital_flow)
    dynamic_score = base_score + flow_adjustment
    
    # 3. 动态阈值调整（基于STI温度）
    sti_phase = await get_current_sti_phase()
    thresholds = get_dynamic_thresholds(sti_phase)
    
    # 4. 判定风险等级
    if dynamic_score >= thresholds["high"]:
        risk_level = "HIGH"
    elif dynamic_score >= thresholds["medium"]:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    
    return OneDayRisk(
        risk_score=dynamic_score,
        risk_level=risk_level,
        last_updated=datetime.now().isoformat(),
        ...
    )
```

**影响范围**：§4.13.1, §4.13.2, §4.13.3, §4.13.4

---

### BLOCKER-3：性能三层拆分

**问题**：§8.1 性能指标混在一起，无法针对性优化，也无法准确定位瓶颈。

**修复方案**：

```python
# 性能三层拆分模型
class PerformanceTiers:
    """性能三层拆分"""
    
    # 第一层：数据获取层（目标 <8s）
    DATA_FETCH = {
        "target": 8.0,  # 秒
        "components": {
            "http_request": "并发批量请求（asyncio.gather）",
            "parsing": "增量解析，避免全量重处理",
            "caching": "TTL缓存 + 本地SQLite兜底",
        }
    }
    
    # 第二层：计算层（目标 <60s）
    COMPUTE = {
        "target": 60.0,  # 秒
        "components": {
            "gene_scoring": "五因子并行计算",
            "sti_calculation": "九维加权 + 百分位归一化",
            "recommendation": "推荐等级 + 仓位建议",
            "risk_assessment": "一日游风险 + 战法匹配",
        }
    }
    
    # 第三层：展示层（目标 <500ms）
    API_RESPONSE = {
        "target": 0.5,  # 秒
        "components": {
            "query": "数据库索引优化",
            "serialization": "Pydantic模型缓存",
            "transport": "HTTP/2 + gzip压缩",
        }
    }
```

**性能监控指标**：

```python
# 新增性能监控端点
PERFORMANCE_METRICS = {
    "/api/metrics/data_fetch": "数据获取层耗时",
    "/api/metrics/compute": "计算层耗时",
    "/api/metrics/api_response": "API响应耗时",
    "/api/metrics/breakdown": "三层拆分详情",
}
```

**§8.1 更新**：

| 指标 | V1.6目标 | V2.0目标 | 分层目标 |
|------|---------|---------|---------|
| 全市场分析耗时 | <5分钟 | **<3分钟** | 数据获取<8s + 计算<60s + 展示<500ms |
| 竞价分析延迟 | <3秒 | **<2秒** | 预计算+缓存 |
| 实时轮询间隔 | 5秒 | **3秒** | 异步优化 |
| 内存占用 | <500MB | **<300MB** | 分批处理 |
| API响应时间 | <1秒 | **<500ms** | 数据库索引+缓存 |
| 首屏加载时间 | — | **<2秒** | 代码分割+懒加载 |

**影响范围**：§8.1, §8.4, §5.2

---

### BLOCKER-4：路由重构（app.py 拆分为 routers/）

**问题**：`backend/app.py` 单文件承载 64 个路由（~1242 行），违反单一职责原则，导致：
- 路由逻辑与业务逻辑混杂，难以定位问题
- 新增模块需修改同一文件，合并冲突概率高
- 单元测试需加载整个 app.py，启动慢、依赖重
- 代码审查 diff 过大，难以聚焦

**修复方案**：

```
backend/
├── app.py                    # 主入口（CORS、中间件、路由聚合）
├── routers/
│   ├── __init__.py
│   ├── health.py             # /api/health
│   ├── chat.py               # /api/chat（流式）
│   ├── portfolio.py          # /api/portfolio/*
│   ├── watchlist.py          # /api/watchlist/*
│   ├── myreports.py          # /api/myreports/*
│   ├── radar.py              # /api/radar/*
│   ├── market.py             # /api/market/*、/api/global/*、/api/indices
│   ├── stock.py              # /api/quote、/api/kline、/api/valuation、/api/financials 等个股数据
│   ├── limitup/
│   │   ├── __init__.py
│   │   ├── screener.py       # /api/limitup/screener、/api/limitup/screener/params
│   │   ├── analysis.py       # /api/limitup/analysis/{code}
│   │   ├── auction.py        # /api/limitup/auction/*
│   │   ├── seats.py          # /api/limitup/seats/*
│   │   └── strategy.py       # 策略逻辑（供 analysis 调用）
│   ├── review.py             # /api/review/*
│   └── sti.py                # /api/market/sti/*
```

**拆分原则**：
1. **按领域分组**：同一业务域的端点放在同一 router（如 limitup 相关全放 `routers/limitup/`）
2. **最小化导入**：每个 router 只导入自己需要的业务模块，减少 app.py 的启动依赖
3. **保持向后兼容**：所有路由路径不变，前端无需修改
4. **渐进式迁移**：先拆分出独立模块（health、chat），再逐步迁移其他路由

**实施步骤**：

| Phase | 任务 | 文件 | 预估工时 |
|-------|------|------|---------|
| 1 | 创建 `routers/` 目录结构，提取 `health.py`、`chat.py` | +2 | 0.5d |
| 2 | 提取 `portfolio.py`、`watchlist.py`、`myreports.py` | +3 | 1d |
| 3 | 提取 `market.py`、`stock.py`、`radar.py` | +3 | 1d |
| 4 | 提取 `limitup/` 子模块（screener、analysis、auction、seats） | +4 | 1.5d |
| 5 | 提取 `review.py`、`sti.py`，清理 app.py 主入口 | +2 | 0.5d |
| 6 | 更新测试、验证所有路由路径 | — | 0.5d |

**验证标准**：
- `curl /api/health` 返回 200
- 所有 64 个路由路径保持不变
- `pytest` 全部通过
- `app.py` 行数降至 <200 行（仅中间件 + 路由聚合）

**风险与缓解**：
- **风险**：拆分过程中遗漏路由或导入错误
- **缓解**：使用 `grep '"@app.get"'` 和 `grep '"@app.post"'` 生成路由清单，逐项核对
- **风险**：循环导入（如 seat_engine 依赖 limitup_screener）
- **缓解**：在 router 层只做路由聚合，业务逻辑保留在原模块，通过依赖注入解决循环

**§5.2 架构图更新**：

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Main (app.py <200行)               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ CORS        │  │ Auth        │  │ Router Aggregation  │  │
│  │ Middleware  │  │ Middleware  │  │ (include_router)    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
    ┌───────────────┐ ┌───────────┐ ┌───────────────┐
    │ routers/      │ │ routers/  │ │ routers/      │
    │ limitup/      │ │ market/   │ │ portfolio/    │
    │ ├── screener  │ │ ├── sti   │ │ ├── holdings  │
    │ ├── analysis  │ │ ├── emotion│ │ ├── close     │
    │ ├── auction   │ │ └── ...   │ │ └── refresh   │
    │ ├── seats     │ │           │ │               │
    │ └── strategy  │ │           │ │               │
    └───────────────┘ └───────────┘ └───────────────┘
```

**影响范围**：§5.2, §8.1, §10.1

---



1. [产品概述](#1-产品概述)
2. [现有基础盘点](#2-现有基础盘点)
3. [三维度升级策略](#3-三维度升级策略)
4. [功能模块设计](#4-功能模块设计)
5. [架构设计](#5-架构设计)
6. [API 设计](#6-api-设计)
7. [配置系统](#7-配置系统)
8. [非功能需求](#8-非功能需求)
9. [合规验证](#9-合规验证)
10. [实施路线图](#10-实施路线图)
11. [核心原则](#11-核心原则)
12. [附录](#12-附录)

---

## 1. 产品概述

### 1.1 产品愿景

Vibe-Research 从"个人 AI 投研看板"演进为"**个人 AI 投研助手**"——不仅展示数据，更主动为量化研究员提供**信息推送、策略建议、异常预警**三大核心能力。

**演进路径**：

```
Phase 0 (V1.x)          Phase 1 (V2.0)            Phase 2 (V2.x+)
被动查询型投研看板  →    主动推送型投研助手    →    盘中交易助手
(已实现)                  (本次目标)                  (未来规划)
```

| 维度 | 投研看板 (V1.x) | 投研助手 (V2.0) | 盘中交易助手 (V2.x+) |
|------|-----------------|-----------------|---------------------|
| **信息获取** | 用户主动查询 | 系统主动推送 | 实时流式推送 |
| **决策支持** | 展示客观数据 | 教育研究式建议 | 半自动化执行 |
| **交互模式** | 页面浏览 | 飞书+页面双通道 | 飞书+盘中弹窗 |
| **数据处理** | 盘后批量 | 盘后+盘前+定时 | 实时流 |

### 1.2 三维度升级框架

本次升级从三个维度重构产品能力：

| 维度 | 核心问题 | 关键改进 | 预期效果 |
|------|---------|---------|---------|
| **研究员效率** | 信息过载，手动整理耗时 | 推荐引擎、信息推送、飞书集成 | 日均节省 2+ 小时 |
| **大数据吞吐** | 3000+ 股票全市场分析性能瓶颈 | 并发管线、增量计算、预计算调度 | 全市场分析 <3 分钟 |
| **异常边界** | 数据缺失/极端行情/接口变更 | 降级策略、熔断器、健康检查 | 系统可用率 >99.5% |

### 1.3 核心能力矩阵

| 能力 | 来源 | V2.0 状态 | 说明 |
|------|------|----------|------|
| 5因子基因选股 | V1.6 已实现 | **增强** | 增加行业对比维度 |
| STI情绪温度 | V1.6 Section 12.9 | **增强** | 增加环比趋势+异常熔断 |
| 集合竞价分析 | V1.6 Section 4.2 | **增强** | 增加市值分层+取消率监控 |
| 推荐引擎与仓位建议 | DSA借鉴 | **新增** | 教育研究式口吻，非交易建议 |
| 集合竞价监控 | DSA借鉴 | **新增** | 盘前推送竞价信号快照 |
| 飞书推送 | DSA借鉴 | **新增** | 投研信息推送能力 |
| XGBoost AI过滤 | DSA借鉴 | **新增** | 多维度ML预测 |
| 游资席位引擎 | V1.6 Section 12.9 | **增强** | 9大游资详细追踪 |
| 每日复盘 | V1.6 Section 12.9 | **增强** | 增加板块轮动+情绪复盘 |
| 个股深度页 | V1.6 Section 12.9 | **增强** | 整合K线+资金+龙虎榜+AI摘要 |
| 简化版回测 | V1.6 Section 12.9 | **新增** | 基因得分 vs 次日表现散点图 |
| 战法信号系统 | DSA借鉴 | **新增** | 8大战法信号+入场价/止损/止盈/持仓天数/成功率 |
| 胜率追踪与策略调整 | DSA借鉴 | **新增** | 滚动胜率10/20/30笔+板块拆分+趋势判断+自动调参 |
| 一日游风险检测 | DSA借鉴 | **新增** | 资金流+龙虎榜席位特征综合评分 |
| 板块情绪分化度 | DSA借鉴 | **新增** | 板块间情绪分化度指标，识别分化市 |

---

## 2. 现有基础盘点

### 2.1 已实现模块

| 模块 | 文件 | 行数 | 状态 | 核心能力 |
|------|------|------|------|---------|
| 基因选股器 | `backend/limitup_screener.py` | 346 | ✅ 生产 | Wilson区间校正、5因子计算、TTL缓存、并发锁 |
| 策略展示 | `backend/limitup_strategy.py` | 300 | ✅ 生产 | 条件匹配、风控规则知识、教育性表述 |
| STI情绪引擎 | `backend/limitup_sti.py` | — | ✅ 生产 | 8维加权STI、5阶段标签、预计算入库 |
| 竞价分析 | `backend/auction_screener.py` | — | ✅ 生产 | 历史竞价数据批量分析 |
| 席位引擎 | `backend/seat_engine.py` | — | ✅ 生产 | 90-180天龙虎榜回溯、席位标签库 |
| 复盘报告 | `backend/daily_review.py` | — | ✅ 生产 | 情绪/板块/个股复盘（规则引擎） |
| 打板策略页 | `frontend/src/pages/LimitUpStrategy.tsx` | 845 | ✅ 生产 | 雷达图+条件匹配+风控知识 |
| 复盘页 | `frontend/src/pages/DailyReview.tsx` | 739 | ✅ 生产 | 情绪图表+板块热力+个股复盘 |
| 个股深度页 | `frontend/src/pages/StockDeep.tsx` | — | ✅ 生产 | K线SVG+资金流+龙虎榜 |

### 2.2 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端 | FastAPI + Python 3.11+ | `backend/app.py` (~1240行路由) |
| 数据层 | 东财HTTP API (`astock.py` ~830行) | `_cached()` 缓存, akshare 已移除 |
| 前端 | React 19 + Vite + Tailwind CSS | `GlassCard`, `cn()`, 红涨绿跌 |
| 存储 | SQLite | 本地存储，零运维 |
| 容器 | Docker + docker-compose | 一键部署 |
| API模式 | `{"data": ...}` 包装 | 前端 `request<T>()` 自动解包 |

### 2.3 DSA优秀实践借鉴

以下功能借鉴自 `daily-stock-analysis` 项目，作为 V2.0 新增模块的参考设计：

| DSA模块 | 参考文件 | 借鉴要点 | V2.0对应 |
|---------|---------|---------|---------|
| 推荐引擎 | `seal_plate_analyzer.py` | 基因得分→推荐等级→仓位百分比，教育研究式口吻 | §4.3 推荐引擎 |
| 竞价监控 | `bidding_monitor.py` | 9:15-9:25实时监控，竞价量/额/取消率三维信号 | §4.4 竞价监控 |
| 飞书推送 | `daily_feishu_notifier.py` | Markdown卡片模板、信号去重、推送节流 | §4.9 信息推送 |
| XGBoost过滤 | `seal_plate_analyzer.py` (AI部分) | 20+特征工程、OOS验证、模型自动重训 | §4.8 ML过滤引擎（🔮未来方向，当前暂不实现） |
| 游资追踪 | `seal_plate.py` (席位部分) | 9大活跃游资详细追踪、席位标签系统 | §4.5 席位引擎 |

---

## 3. 三维度升级策略

### 3.1 维度一：研究员效率提升

**目标**：量化研究员日均节省 2+ 小时手动整理时间

| 改进项 | 当前痛点 | 解决方案 | 预期效果 |
|--------|---------|---------|---------|
| 推荐引擎 | 手动筛选3000+股票 | 自动基因评分→推荐等级→仓位建议 | 筛选时间 60min→5min |
| 信息推送 | 手动刷新页面查看更新 | 飞书自动推送关键信号 | 减少80%主动查询 |
| 集合竞价监控 | 9:15-9:25手动盯盘 | 系统自动监控+信号推送 | 不再错过竞价窗口 |
| 复盘自动化 | 手动整理当日数据 | 盘后自动生成复盘报告 | 复盘时间 30min→0 |
| 个股深度整合 | 跨页面切换查看 | 单页面整合K线/资金/龙虎榜 | 个股研究时间减半 |

### 3.2 维度二：大数据吞吐优化

**目标**：全市场 3000+ 股票分析 <3 分钟

| 改进项 | 当前瓶颈 | 解决方案 | 预期效果 |
|--------|---------|---------|---------|
| 并发数据获取 | 串行HTTP请求 | `asyncio.gather` 批量并发 | 数据获取 44s→8s |
| 增量计算 | 每次全量重算 | 增量更新（只计算新数据） | 重复计算 -90% |
| 预计算调度 | 用时触发计算 | 定时任务预计算+缓存 | 查询延迟 <100ms |
| 内存优化 | 全量数据驻留 | 分批处理+及时释放 | 内存占用 <300MB |
| 数据库索引 | 无索引全表扫描 | 关键查询添加索引 | 查询速度 3x |

### 3.3 维度三：异常边界完善

**目标**：系统可用率 >99.5%，异常不阻塞核心流程

| 改进项 | 当前风险 | 解决方案 | 预期效果 |
|--------|---------|---------|---------|
| 数据源降级 | 东财接口故障时无数据 | 多源冗余+本地缓存兜底 | 数据可用率 >99% |
| 熔断器 | 接口超时导致线程阻塞 | 熔断器模式(fail-fast) | 超时不再扩散 |
| 极端行情 | 涨停潮/跌停潮数据异常 | 动态阈值+异常值过滤 | 极端行情不崩溃 |
| 模型退化 | AI模型过拟合或失效 | OOS监控+自动告警+回滚 | 模型失效 <24h发现 |
| 健康检查 | 系统异常无人知道 | 端点健康检查+飞书告警 | 异常 <5min发现 |
| 配置验证 | 错误配置导致运行时崩溃 | 启动时配置校验 | 配置错误 0 发生 |

---

## 4. 功能模块设计

### 4.1 STI情绪温度引擎（增强）

> **文件**：`backend/limitup_sti.py`  
> **定位**：市场情绪的客观温度计，用于择时参考

#### 4.1.1 九维指标体系（V2.0 增强版）

在 V1.6 的 8 维加权基础上，增加**环比趋势维度**：

| 序号 | 指标 | 权重 | 数据来源 | V2.0变更 |
|------|------|------|---------|---------|
| 1 | 封板率 seal_rate | 0.25 | 涨停板四池 | 保留 |
| 2 | 涨停家数 limit_up_count | 0.15 | `em_zt_topic_pool` | 保留 |
| 3 | 涨跌比 up_down_ratio | 0.12 | 市场统计 | 保留 |
| 4 | 昨日涨停表现 prev_zt_performance | 0.12 | T-1溢价率 | 保留 |
| 5 | 平均涨停溢价 avg_premium | 0.10 | 涨停池溢价 | 保留 |
| 6 | 连板高度 board_height | 0.10 | 最高连板数 | 保留 |
| 7 | 北向资金 north_flow | 0.08 | 北向数据 | 保留 |
| 8 | 换手率 turnover | 0.08 | 市场统计 | 保留 |
| **9** | **STI环比趋势 sti_delta** | **新增** | **T-1 vs T-2 STI差值** | **新增** |
| F | 板块集中度 sector_concentration | 过滤器 | 板块分布 | 保留 |

**环比趋势计算**：
```python
sti_delta = sti_today - sti_yesterday
# 用于辅助判断情绪拐点：连续3日sti_delta > 0 → 温度上升趋势
# 不参与加权计算，作为独立辅助信号
```

#### 4.1.2 动态阈值与异常熔断

```python
# 动态阈值：基于252日滚动分位数（与现有代码一致）
P10, P25, P75, P90 = rolling_percentiles(sti_history, window=252)

# 五阶段标签
phases = {
    "冰点": (< P10,  "#1e3a5f"),   # 深蓝
    "退潮": (P10-P25, "#2d5a7b"),  # 蓝灰
    "震荡": (P25-P75, "#4a7c59"),  # 灰绿
    "升温": (P75-P90, "#c45a3c"),  # 橙红
    "过热": (> P90,   "#8b1a1a"),  # 深红
}

# 异常熔断：source_ok=False 时返回 null，不伪造分数
if not source_ok:
    return STIResult(score=None, phase=None, source_ok=False)
```

#### 4.1.3 增量预计算

```python
# 每日15:30触发预计算
async def precompute_sti(date: str):
    """增量计算当日STI，写入SQLite sti_timeline表"""
    # 1. 检查是否已计算（防重复）
    # 2. 获取9维原始数据
    # 3. 百分位归一化
    # 4. 加权合成
    # 5. 阶段判定
    # 6. 写入数据库
    # 耗时目标：<10秒（增量模式）
```

---

### 4.1.5 情绪气象站（Sentiment Weather Station）（新增）

> **文件**：
> - 后端：`backend/routers/sentiment_weather.py`
> - 前端：`frontend/src/pages/sentiment/SentimentWeather.tsx`
> - UI 设计：`docs/sentiment-weather-station-ui-design.md`
>
> **定位**：市场情绪天气可视化中枢，通过多因子加权模型将抽象的情绪数据转化为直观的天气隐喻，动态指挥打板策略切换。

#### 4.1.5.1 核心设计理念

情绪气象站是 Vibe-Research 的**策略控制中枢**，解决当前系统缺少"市场环境判断 → 策略自动匹配"闭环的问题。用户无需手动判断当前是牛市、震荡市还是退潮期，系统通过客观数据自动识别并推荐最佳打板风格。

#### 4.1.5.2 四种市场天气状态

| 天气状态 | 核心判断指标 | 推荐打板风格 | 系统动作 |
|---------|------------|------------|---------|
| ⛈️ 暴风雨（退潮期） | 炸板率 > 40%、连板高度 < 3板、跌停家数 > 20家 | 空仓观望 | 自动锁死交易权限，禁止任何买入条件单 |
| ⛅ 阴天（震荡轮动） | 涨停家数 < 50家、无明显主线、前日龙头次日多低开 | 首板挖掘（低位套利） | 激活首板监控池，过滤高位接力 |
| ☀️ 晴天（主线主升） | 涨停家数 > 80家、连板高度不断抬升、赚钱效应扩散 | 连板接力（高位数板） | 激活连板监控池，追逐龙头 |
| 🌪️ 极端反弹（冰点反转） | 市场经历大跌后某大题材集体爆发、跌停集体打开 | 弱转强反包 / 情绪反包 | 激活反包监控池，捕捉反转信号 |

#### 4.1.5.3 多因子加权评分模型

综合评分 = STI 情绪温度 × 40% + 风险指标 × 20% + 板块持续性 × 25% + 资金动量 × 10% + 舆情情绪 × 5%

| 因子 | 权重 | 数据来源 | 计算逻辑 |
|------|------|---------|---------|
| STI 情绪温度 | 40% | 现有 STI 引擎（8维加权） | 直接使用 STI 分数（0-100） |
| 风险指标 | 20% | 炸板率、跌停家数、连板高度 | 风险越低分数越高：100 - (跌停惩罚 + 封板率惩罚 + 连板惩罚) |
| 板块持续性 | 25% | 板块涨停家数、资金流向 | 涨跌比 × 30 归一化 |
| 资金动量 | 10% | 成交额变化、龙虎榜 | STI 环比变化 × 2 + 50 |
| 舆情情绪 | 5% | 社交媒体、新闻情绪 | 预留接口，当前返回中性值 50 |

**天气判定阈值**：
- 综合评分 ≥ 75 → 晴天
- 55 ≤ 综合评分 < 75 → 阴天
- 35 ≤ 综合评分 < 55 → 极端反弹
- 综合评分 < 35 → 暴风雨

#### 4.1.5.4 半自动工作流（5步）

```
[步骤 1: 盘前数据扫描]
       ↓
[步骤 2: 自动计算情绪天气] ───→ 自动下发【今日允许打板风格指令】
       ↓
[步骤 3: 触发对应选股公式池] ──→ 自动将符合风格的标的加入【临盘监控池】
       ↓
[步骤 4: 盘中分时触发预警] ───→ 系统弹出提示、自动填好涨停价、数量（人工一键确认）
       ↓
[步骤 5: 次日自动执行断板流] ──→ 监控竞价，不符合预期自动挂单单清仓
```

#### 4.1.5.5 三大风格切换配置

**风格 A：连板接力模式（晴天/主升浪）**
- 核心逻辑：强者恒强，追逐市场的最高板、妖股
- 过滤规则：2连板以上 + 主线板块成交额前三 + 板块涨停≥3只
- 条件单设置：触发条件为价格 ≥ 涨停价 - 0.02元 且 五档卖盘萎缩，执行动作为弹窗提示 + 人工确认后涨停价扫货

**风格 B：首板挖掘模式（阴天/轮动市）**
- 核心逻辑：高位连板容易吃面，只打低位第一个涨停板，赚次日溢价就跑
- 过滤规则：过去20日未连板 + 当日异动拉升 + 有突发利好催化
- 条件单设置：触发条件为分时大单点火（5倍均量）且涨幅 7.5%-9%，执行动作为加入急速雷达监控 + 自动计算封板买入金额

**风格 C：弱转强/反包板模式（极端反弹/冰点期结束）**
- 核心逻辑：前一日表现很弱，次日突然超级高开，完成情绪反转
- 过滤规则：前日长上影/跌停 + 今日竞价高开 3%+ + 竞价成交量超昨日5分钟总和
- 条件单设置：触发条件为开盘3分钟内冲过昨日最高价，执行动作为触发"弱转强"预警 + 通知交易员准备切入

#### 4.1.5.6 三条熔断规则（硬性闭环）

1. **仓位熔断**：当情绪气象站判定为"暴风雨"，系统自动锁死交易权限，禁止下发任何买入条件单
2. **撤单熔断**：排板时，如果五档盘口的封单金额跌破 3000 万，或者撤单量/封单量 > 20%，系统必须自动执行撤单，无需人工确认
3. **次日强制离场**：次日 09:25 竞价结束，若股票未高开（≤0%）或开盘 5 分钟内无法站稳均线，系统直接自动生成市价卖出单，交易员只需按下"确定"即可完成止损

#### 4.1.5.7 前端页面设计

**路由**：`/sentiment/weather`（主页面） + 二级路由：
- `/sentiment/weather` - 实时天气（默认）
- `/sentiment/weather/history` - 历史趋势
- `/sentiment/weather/strategy` - 策略建议
- `/sentiment/weather/fuse` - 熔断规则

**侧边栏**：在"市场概览"组新增"情绪气象"入口

**二级导航**：实时天气 | 历史趋势 | 策略建议 | 熔断规则

**核心组件**：
- **WeatherHero**：天气状态大卡片，展示当前天气、STI 温度计、情绪指数、置信度
- **MultiFactorBreakdown**：多因子情绪分解，展示 5 个因子的加权评分和贡献度
- **StrategyRecommendation**：策略推荐卡片，根据当前天气推荐最佳打板策略
- **FuseRulesPanel**：熔断规则监控，展示 3 条熔断规则的当前状态
- **WeatherTimelineChart**：天气历史趋势图（ECharts）

**视觉设计**：
- 暴风雨：深灰蓝渐变背景，红色警示
- 阴天：浅灰蓝渐变，云朵图标
- 晴天：暖橙渐变，太阳图标
- 极端反弹：紫红渐变，闪电图标

#### 4.1.5.8 后端 API 设计

| 端点 | 方法 | 职责 |
|------|------|------|
| `/api/sentiment/weather/latest` | GET | 获取当前天气状态 + 综合评分 + 置信度 |
| `/api/sentiment/weather/factors` | GET | 获取多因子详细数据（用于分解图表） |
| `/api/sentiment/weather/strategy` | GET | 获取当前天气下的策略推荐 |
| `/api/sentiment/weather/fuse` | GET | 获取熔断规则状态 |
| `/api/sentiment/weather/timeline` | GET | 获取历史趋势数据（近 N 天） |
| `/api/sentiment/weather/events` | GET | 获取关键事件标注（政策/利好/利空） |

**数据源**：
- STI 数据：复用现有 `limitup_sti` 引擎和 `sti_timeline` 表
- 风险指标：基于 STI 维度（跌停家数、封板率、连板高度）计算
- 板块持续性：基于涨跌比推算
- 资金动量：基于 STI 环比变化推算
- 舆情情绪：预留接口，当前返回中性值

#### 4.1.5.9 与现有系统集成

- **数据层**：直接读取 `sti_timeline` 表，不修改现有 STI 引擎
- **API 层**：独立路由器 `sentiment_weather.py`，通过 `app.py` 注册
- **前端层**：独立页面 `SentimentWeather.tsx`，通过路由挂载到 Layout
- **导航层**：侧边栏"市场概览"组 + 二级 Tab 栏
- **解耦保证**：所有计算在独立模块完成，不侵入现有业务逻辑

#### 4.1.5.10 数据模型

**天气状态表**（`sentiment_weather_states`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| weather_date | DATE | 日期 |
| weather_state | VARCHAR(20) | 天气状态：暴风雨/阴天/晴天/极端反弹 |
| composite_score | FLOAT | 综合评分 0-100 |
| confidence | VARCHAR(10) | 置信度：高/中/低 |
| sti_score | FLOAT | STI 情绪温度 0-100 |
| sti_phase | VARCHAR(20) | STI 阶段：冰点/启动/分歧/高潮/退潮 |
| risk_score | FLOAT | 风险指标 0-100 |
| sector_continuity_score | FLOAT | 板块持续性 0-100 |
| capital_momentum_score | FLOAT | 资金动量 0-100 |
| public_sentiment_score | FLOAT | 舆情情绪 0-100 |
| recommended_strategy | VARCHAR(50) | 推荐策略 |
| data_updated | DATETIME | 数据更新时间 |
| created_at | DATETIME | 记录创建时间 |

**天气历史表**（`sentiment_weather_timeline`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| weather_date | DATE | 日期 |
| weather_state | VARCHAR(20) | 天气状态 |
| composite_score | FLOAT | 综合评分 |
| sti_score | FLOAT | STI 分数 |
| events | JSON | 关键事件标注（政策/利好/利空） |

**熔断规则配置表**（`sentiment_fuse_rules`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT | 主键 |
| rule_name | VARCHAR(50) | 规则名称 |
| rule_type | VARCHAR(20) | 规则类型：position/cancel/exit |
| enabled | BOOLEAN | 是否启用 |
| trigger_condition | TEXT | 触发条件描述 |
| threshold_value | JSON | 阈值参数（JSON 格式） |
| action | TEXT | 执行动作 |
| updated_at | DATETIME | 更新时间 |

#### 4.1.5.11 错误处理与边缘情况

1. **数据缺失**：当 STI 数据未更新时，返回 `source_ok=false`，前端显示"数据暂未更新" + 最后可用时间
2. **计算失败**：当因子计算异常时，记录错误日志，返回降级结果（使用历史均值或中性值）
3. **并发保护**：使用 `_COMPUTING` 锁机制，避免重复计算
4. **缓存策略**：5 分钟缓存，缓存失效时返回旧数据 + 警告提示
5. **边界条件**：
   - 综合评分 < 0 或 > 100 时，截断到有效范围
   - 权重总和不为 1 时，自动归一化
   - 缺失因子使用剩余因子加权平均填充

#### 4.1.5.12 性能要求

- **计算耗时**：增量预计算 < 10 秒（基于现有 STI 数据）
- **API 响应**：P95 < 500ms，P99 < 1000ms
- **前端渲染**：首屏加载 < 2 秒，交互响应 < 100ms
- **数据更新**：支持 5 分钟自动刷新，手动刷新 < 3 秒

#### 4.1.5.15 关键风险控制修正（V2.0.3 BLOCKER修复）

> **审查来源**：用户审查 + Oracle审查补充  
> **修复日期**：2026-07-23  
> **状态**：待实施验证

##### 4.1.5.15.1 日内数据延迟与死循环防护

**问题**：实时数据可能存在延迟，导致系统基于过时数据反复触发条件单，形成死循环。

**修复方案**：
```python
# 数据新鲜度校验
DATA_FRESHNESS = {
    "max_delay_sec": 5,           # 最大允许延迟（秒）
    "stale_threshold_sec": 10,    # 超过此阈值标记为过期
    "dead_loop_guard": {
        "max_trigger_count": 3,   # 单票单日最大触发次数（窗口内）
        "window_sec": 300,        # 统计窗口：5分钟（与前端显示一致）
        "cooldown_sec": 60,       # 触发后冷却时间
        "price_deviation_pct": 0.02  # 价格偏离超过2%强制校验
    }
}

async def validate_data_freshness(
    timestamp: datetime,
    current_price: float,
    trigger_price: float
) -> tuple[bool, str]:
    """
    校验数据新鲜度，防止基于过期数据决策
    
    Returns:
        (is_valid, reason): 是否有效及原因
    """
    now = datetime.now()
    delay = (now - timestamp).total_seconds()
    
    # 检查数据延迟
    if delay > DATA_FRESHNESS["stale_threshold_sec"]:
        return False, f"数据过期（延迟{delay:.1f}秒）"
    
    # 检查价格偏离（死循环防护）
    if trigger_price > 0 and current_price > 0:
        deviation = abs(current_price - trigger_price) / trigger_price
        if deviation > DATA_FRESHNESS["dead_loop_guard"]["price_deviation_pct"]:
            return False, f"价格偏离过大（{deviation:.1%}），可能处于死循环"
    
    return True, "数据有效"

async def check_dead_loop_guard(
    stock_code: str,
    trigger_count: int,
    window_sec: int = 300
) -> tuple[bool, str]:
    """
    死循环检测：同一股票在统计窗口内触发次数限制
    
    Returns:
        (is_allowed, reason): 是否允许触发及原因
    """
    guard = DATA_FRESHNESS["dead_loop_guard"]
    
    if trigger_count >= guard["max_trigger_count"]:
        return False, f"单票{window_sec}秒内触发次数已达上限（{trigger_count}/{guard['max_trigger_count']}）"
    
    return True, "允许触发"

# 过期数据行为定义
STALE_DATA_BEHAVIOR = {
    "cancel_pending_orders": True,   # 取消待成交条件单
    "halt_new_entries": True,        # 停止新条件单入场
    "alert_user": True,              # 通知用户
    "queue_for_retry": False,        # 不排队重试（防止死循环）
    "lock_stock_sec": 600            # 锁定股票10分钟
}
```

**前端防护**：
- 数据时间戳显示：`最后更新: 2026-07-23 15:05:03 (延迟2秒)`
- 过期数据警告：黄色警示条 + 禁用条件单触发按钮
- 死循环检测：同一股票5分钟内触发超过3次，自动锁定并通知用户
- 锁定状态显示：`🔒 已锁定（剩余8分钟）`

##### 4.1.5.15.2 A股通道速度与滑点补偿

**问题**：条件单执行逻辑未考虑A股T+1、涨跌停、通道速度限制，可能导致实际成交价格与预期不符。

**修复方案**：
```python
# A股通道执行参数
A_SHARE_EXECUTION = {
    "t+1_settlement": True,      # T+1结算，当日买入不可卖出
    "price_limit_pct": 0.10,     # 涨跌停10%限制（ST股5%）
    "tick_size": 0.01,           # A股最小价格变动单位：0.01元
    "channel_latency": {
        "call_auction_ms": 300,  # 竞价阶段通道延迟（9:15-9:25）
        "continuous_trading_ms": 200,  # 连续交易阶段通道延迟（9:30-11:30, 13:00-15:00）
        "retail_broker_ms": 500, # 零售券商通道延迟上限
        "institutional_ms": 100  # 机构席位通道延迟上限
    },
    "slippage_compensation": {
        "buy_slippage": 0.001,    # 买入滑点补偿0.1%
        "sell_slippage": 0.001,   # 卖出滑点补偿0.1%
        "limit_up_slippage": 0.005,  # 涨停板滑点补偿0.5%
        "limit_down_slippage": 0.005 # 跌停板滑点补偿0.5%
    },
    "volume_check": {
        "min_volume_ratio": 0.3,  # 最小成交量占比30%
        "max_volume_ratio": 5.0   # 最大成交量占比500%
    },
    "commission": {
        "buy_rate": 0.00025,      # 买入佣金万2.5
        "sell_rate": 0.00025,     # 卖出佣金万2.5
        "stamp_tax": 0.0005,      # 印花税0.05%（卖出时收取）
        "transfer_fee": 0.00002   # 过户费0.002%
    }
}

def adjust_order_price(
    base_price: float,
    side: str,
    market_state: str,
    phase: str = "continuous",
    broker_type: str = "retail"
) -> float:
    """
    根据A股通道特性调整委托价格
    
    Args:
        base_price: 基准价格
        side: 买卖方向（buy/sell）
        market_state: 市场状态（normal/limit_up/limit_down）
        phase: 交易阶段（call_auction/continuous）
        broker_type: 券商类型（retail/institutional）
    
    Returns:
        调整后的委托价格（已四舍五入到0.01元）
    """
    # 获取通道延迟
    if phase == "call_auction":
        latency = A_SHARE_EXECUTION["channel_latency"]["call_auction_ms"]
    else:
        latency = A_SHARE_EXECUTION["channel_latency"]["continuous_trading_ms"]
    
    # 根据券商类型调整延迟
    if broker_type == "institutional":
        latency = min(latency, A_SHARE_EXECUTION["channel_latency"]["institutional_ms"])
    else:
        latency = max(latency, A_SHARE_EXECUTION["channel_latency"]["retail_broker_ms"])
    
    # 计算滑点补偿
    slippage = A_SHARE_EXECUTION["slippage_compensation"]
    if side == "buy":
        if market_state == "limit_up":
            adjusted = base_price * (1 + slippage["limit_up_slippage"])
        else:
            adjusted = base_price * (1 + slippage["buy_slippage"])
    else:
        if market_state == "limit_down":
            adjusted = base_price * (1 - slippage["limit_down_slippage"])
        else:
            adjusted = base_price * (1 - slippage["sell_slippage"])
    
    # 涨跌停价格校验
    limit_up = base_price * (1 + A_SHARE_EXECUTION["price_limit_pct"])
    limit_down = base_price * (1 - A_SHARE_EXECUTION["price_limit_pct"])
    adjusted = max(min(adjusted, limit_up), limit_down)
    
    # 最小价格变动单位四舍五入
    adjusted = round(adjusted / A_SHARE_EXECUTION["tick_size"]) * A_SHARE_EXECUTION["tick_size"]
    
    return adjusted

def calc_volume_check(
    order_volume: float,
    auction_volume: float,
    daily_avg_volume: float
) -> tuple[bool, str]:
    """
    成交量校验：确保订单量在合理范围内
    
    Returns:
        (is_valid, reason): 是否有效及原因
    """
    check = A_SHARE_EXECUTION["volume_check"]
    
    if daily_avg_volume > 0:
        volume_ratio = order_volume / daily_avg_volume
        if volume_ratio < check["min_volume_ratio"]:
            return False, f"成交量过低（{volume_ratio:.1%} < {check['min_volume_ratio']:.0%}）"
        if volume_ratio > check["max_volume_ratio"]:
            return False, f"成交量过高（{volume_ratio:.1%} > {check['max_volume_ratio']:.0%}）"
    
    return True, "成交量正常"
```

**前端展示**：
- 条件单配置中显示预估成交价（含滑点补偿）：`预估买入价: ¥10.05 (含滑点0.1%)`
- 通道延迟实时显示：`通道延迟: 300ms (竞价阶段)`
- 滑点预估：`预估滑点: ±0.1% (涨停板: ±0.5%)`
- 成交量校验：`成交量: 1.2倍日均量 ✓`

##### 4.1.5.15.3 结算买入价逻辑悖论修正

**问题**：当前逻辑中，结算买入价的计算存在悖论——使用"买入价"作为结算基准，但T+1规则下当日买入不可卖出，导致次日卖出时的成本计算混乱。

**修复方案**：
```python
# 结算买入价计算（修正版）
SETTLEMENT_PRICE_LOGIC = {
    "use_auction_price": True,    # 使用竞价成交价作为买入价
    "fallback_to_open": True,     # 竞价无成交时使用开盘价
    "fallback_to_prev_close": True,  # 无开盘价时使用前收盘价（非涨停价）
    "t+1_lock": True,             # T+1锁定，当日不可卖出
    "next_day_sell_base": "prev_close_adj"  # 次日卖出基准：前收盘价调整
}

def calc_settlement_buy_price(
    order_trigger_price: float,
    auction_price: float,
    open_price: float,
    prev_close: float,
    limit_up: float,
    limit_down: float
) -> tuple[float, str]:
    """
    计算实际结算买入价（修正悖论）
    
    Args:
        order_trigger_price: 条件单触发价
        auction_price: 竞价成交价（0表示无成交）
        open_price: 开盘价（0表示无开盘价）
        prev_close: 前收盘价
        limit_up: 涨停价
        limit_down: 跌停价
    
    Returns:
        (settlement_price, source): 结算价及来源说明
    """
    # 校验价格有效性
    if auction_price > 0:
        if not (limit_down <= auction_price <= limit_up):
            return order_trigger_price, "trigger_price (auction out of bounds)"
        return auction_price, "auction_price"
    
    if open_price > 0:
        if not (limit_down <= open_price <= limit_up):
            return order_trigger_price, "trigger_price (open out of bounds)"
        return open_price, "open_price"
    
    # 使用前收盘价作为最终回退（而非涨停价）
    if prev_close > 0:
        return prev_close, "prev_close (fallback)"
    
    # 最终回退：使用触发价
    return order_trigger_price, "trigger_price (last resort)"

def calc_next_day_sell_base(
    next_auction_open: float,
    next_prev_close: float,
    next_limit_up: float,
    next_limit_down: float
) -> tuple[float, str]:
    """
    计算次日卖出基准价
    
    注意：次日卖出基准应为次日竞价开盘价，而非涨停价。
    涨停价是理论上限，实际成交价通常低于涨停价。
    
    Returns:
        (sell_base, source): 卖出基准价及来源说明
    """
    if next_auction_open > 0:
        if not (next_limit_down <= next_auction_open <= next_limit_up):
            return next_prev_close, "prev_close (auction out of bounds)"
        return next_auction_open, "next_auction_open"
    
    # 无次日开盘价时，使用前收盘价调整（保守估计）
    if next_prev_close > 0:
        return next_prev_close * 1.01, "prev_close_adj (+1%)"
    
    return next_limit_down, "limit_down (last resort)"

def calc_total_cost(
    buy_price: float,
    volume: int,
    commission_rate: float = 0.00025,
    stamp_tax_rate: float = 0.0005,
    transfer_fee_rate: float = 0.00002
) -> dict:
    """
    计算交易总成本（含佣金、印花税、过户费）
    
    Returns:
        {
            "buy_amount": 买入金额,
            "commission": 佣金,
            "stamp_tax": 印花税,
            "transfer_fee": 过户费,
            "total_cost": 总成本,
            "effective_price": 实际成交均价
        }
    """
    buy_amount = buy_price * volume
    commission = buy_amount * commission_rate
    stamp_tax = buy_amount * stamp_tax_rate  # 买入时收取（部分券商）
    transfer_fee = buy_amount * transfer_fee_rate
    
    total_cost = buy_amount + commission + stamp_tax + transfer_fee
    effective_price = total_cost / volume if volume > 0 else 0
    
    return {
        "buy_amount": round(buy_amount, 2),
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "total_cost": round(total_cost, 2),
        "effective_price": round(effective_price, 2)
    }
```

**前端展示**：
- 条件单详情显示：`预估买入价: ¥10.05 (竞价成交价)`
- 次日卖出基准：`次日卖出基准: ¥10.08 (次日竞价开盘价)`
- T+1锁定提示：`⚠️ T+1规则：当日买入不可卖出`
- 交易成本明细：`佣金: ¥2.50 | 印花税: ¥5.00 | 过户费: ¥0.20 | 实际均价: ¥10.0527`

##### 4.1.5.15.4 绝对封单额/流通盘风险控制

**问题**：当前熔断规则仅使用相对指标（如封单金额跌破3000万），未考虑个股流通盘大小，导致小盘股风险控制失效。

**修复方案**：
```python
# 绝对封单额/流通盘风险控制
ABSOLUTE_RISK_CONTROL = {
    "min_seal_amount_abs": 5000000,  # 绝对封单额下限：500万元（单位：元）
    "seal_to_float_ratio_min": 0.15, # 封单额/流通盘最低比例：15%
    "float_cap_thresholds": {
        "micro_cap": 50000000,       # 微型股：流通盘 < 5000万股
        "small_cap": 200000000,      # 小盘股：流通盘 < 2亿股
        "mid_cap": 1000000000,       # 中盘股：流通盘 < 10亿股
        "large_cap": 5000000000      # 大盘股：流通盘 >= 10亿股
    },
    "dynamic_adjustment": {
        "micro_cap": 0.25,   # 微型股封单比例要求25%
        "small_cap": 0.20,   # 小盘股封单比例要求20%
        "mid_cap": 0.15,     # 中盘股封单比例要求15%
        "large_cap": 0.10    # 大盘股封单比例要求10%
    },
    "enforcement": {
        "action_on_unsafe": "downgrade_to_watch",  # 不安全时的处理：降级为观察
        "alert_threshold": "high",  # 预警阈值：high
        "auto_cancel": False,  # 不自动撤单（需人工确认）
        "log_all_checks": True  # 记录所有检查
    }
}

def calc_seal_risk(
    stock_code: str,
    seal_amount: float,      # 封单额（单位：元）
    float_shares: float,     # 流通盘（单位：股）
    price: float             # 当前价格（用于校验）
) -> dict:
    """
    计算封单风险（绝对+相对双指标）
    
    Args:
        stock_code: 股票代码
        seal_amount: 封单额（元）
        float_shares: 流通盘（股）
        price: 当前价格（用于校验封单额合理性）
    
    Returns:
        {
            "is_safe": bool,
            "seal_amount": float,
            "float_shares": float,
            "seal_ratio": float,
            "min_ratio_required": float,
            "risk_level": "low" | "medium" | "high",
            "cap_category": str,
            "enforcement_action": str,
            "reason": str
        }
    """
    # 校验输入
    if float_shares <= 0 or price <= 0:
        return {
            "is_safe": False,
            "risk_level": "high",
            "reason": "无效的流通盘或价格数据"
        }
    
    # 计算封单比例
    seal_ratio = seal_amount / (float_shares * price) if (float_shares * price) > 0 else 0
    
    # 根据流通盘大小分类
    thresholds = ABSOLUTE_RISK_CONTROL["float_cap_thresholds"]
    if float_shares < thresholds["micro_cap"]:
        cap_category = "micro_cap"
        min_ratio = ABSOLUTE_RISK_CONTROL["dynamic_adjustment"]["micro_cap"]
    elif float_shares < thresholds["small_cap"]:
        cap_category = "small_cap"
        min_ratio = ABSOLUTE_RISK_CONTROL["dynamic_adjustment"]["small_cap"]
    elif float_shares < thresholds["mid_cap"]:
        cap_category = "mid_cap"
        min_ratio = ABSOLUTE_RISK_CONTROL["dynamic_adjustment"]["mid_cap"]
    else:
        cap_category = "large_cap"
        min_ratio = ABSOLUTE_RISK_CONTROL["dynamic_adjustment"]["large_cap"]
    
    # 双指标校验
    is_safe = (
        seal_amount >= ABSOLUTE_RISK_CONTROL["min_seal_amount_abs"] and
        seal_ratio >= min_ratio
    )
    
    # 确定风险等级
    if is_safe:
        risk_level = "low"
    elif seal_amount >= ABSOLUTE_RISK_CONTROL["min_seal_amount_abs"]:
        risk_level = "medium"  # 绝对金额达标但比例不足
    else:
        risk_level = "high"
    
    # 确定执行动作
    enforcement = ABSOLUTE_RISK_CONTROL["enforcement"]
    if not is_safe:
        action = enforcement["action_on_unsafe"]
    else:
        action = "allow"
    
    return {
        "is_safe": is_safe,
        "seal_amount": seal_amount,
        "float_shares": float_shares,
        "seal_ratio": round(seal_ratio, 4),
        "min_ratio_required": min_ratio,
        "risk_level": risk_level,
        "cap_category": cap_category,
        "enforcement_action": action,
        "reason": f"封单额{seal_amount/10000:.0f}万/流通盘{float_shares/100000000:.2f}亿股，比例{seal_ratio:.1%}，要求≥{min_ratio:.0%}"
    }
```

**前端展示**：
- 封单风险卡片显示：`封单额: ¥500万 / 流通盘: 2亿股 (比例: 2.5%)`
- 风险等级：`🟢 安全` / `🟡 中风险` / `🔴 高风险`
- 动态阈值提示：`小盘股要求封单比例 ≥ 20%`
- 执行动作：`✅ 允许` / `⚠️ 降级为观察` / `🔴 高风险`

##### 4.1.5.15.5 竞价换手率与竞价成交额监控

**新增指标**：在 RealtimeMonitor 中增加竞价阶段核心指标

```python
# 竞价阶段指标（RealtimeMonitor 新增）
AUCTION_METRICS = {
    "call_auction_turnover_rate": {  #  renamed from auction_turnover_rate
        "name": "竞价换手率",
        "formula": "竞价成交量 / 流通盘",
        "phases": {
            "pre_competitive": {  # 9:15-9:20 可撤单阶段
                "threshold_high": 0.03,   # 3%以上为高换手
                "threshold_low": 0.005,   # 0.5%以下为低换手
            },
            "competitive": {  # 9:20-9:25 不可撤单阶段
                "threshold_high": 0.05,   # 5%以上为高换手
                "threshold_low": 0.01,    # 1%以下为低换手
            }
        },
        "unit": "%",
        "data_source_requirement": "必须能区分9:15-9:20和9:20-9:25两个阶段的成交量"
    },
    "call_auction_amount": {
        "name": "竞价成交额",
        "formula": "竞价成交价 × 竞价成交量",
        "phases": {
            "pre_competitive": {
                "threshold_high": 30000000,  # 3000万以上为高成交
                "threshold_low": 500000,     # 50万以下为低成交
            },
            "competitive": {
                "threshold_high": 50000000,  # 5000万以上为高成交
                "threshold_low": 1000000,    # 100万以下为低成交
            }
        },
        "unit": "元",
        "data_source_requirement": "必须能获取分阶段竞价成交额"
    },
    "call_auction_volume_ratio": {
        "name": "竞价量比",
        "formula": "竞价成交量 / 昨日同期成交量",
        "phases": {
            "pre_competitive": {
                "threshold_high": 2.5,     # 2.5倍以上为异常放量
                "threshold_low": 0.3,      # 0.3倍以下为缩量
            },
            "competitive": {
                "threshold_high": 3.0,     # 3倍以上为异常放量
                "threshold_low": 0.5,      # 0.5倍以下为缩量
            }
        },
        "unit": "x",
        "data_source_requirement": "需要历史同期成交量数据"
    }
}
```

**前端展示**：
- RealtimeMonitor 新增卡片：
```
竞价阶段监控 (9:20-9:25 不可撤单阶段)
├── 竞价换手率: 2.3%    ████████████░░░░░░░░░░  阈值: 1%-5%
├── 竞价成交额: ¥1,250万 ████████████░░░░░░░░░░  阈值: 100万-5000万
└── 竞价量比: 2.5x    ████████████░░░░░░░░░░  阈值: 0.5x-3.0x
```
- 阶段切换提示：`当前阶段: 不可撤单阶段 (9:20-9:25)`
- 高亮阈值：超过阈值显示黄色/红色警示

##### 4.1.5.15.6 仓位熔断管理员赦免战法开关

**新增功能**：管理员可对特定战法启用"赦免模式"，在暴风雨天气下仍允许该战法执行。

```python
# 仓位熔断赦免配置
FUSE_PARDON_CONFIG = {
    "enabled": False,  # 默认关闭，需管理员开启
    "allowed_strategies": [],  # 允许赦免的战法列表
    "max_position_pct": 0.35,  # 赦免模式下最大仓位35%（原10%过低）
    "require_dual_approval": True,  # 需要双人审批
    "require_2fa": True,  # 需要2FA验证
    "ip_whitelist": [],  # 管理员IP白名单（可选）
    "log_all_pardon": True,  # 记录所有赦免操作
    "auto_revoke_hours": 24,   # 24小时后自动撤销赦免
    "manual_revoke_enabled": True,  # 允许手动撤销
    "outcome_tracking": True  # 跟踪赦免交易的执行结果
}

@dataclass
class FusePardonRecord:
    """仓位熔断赦免记录"""
    id: str
    strategy_code: str
    strategy_name: str
    enabled_by: str  # 管理员ID
    enabled_ip: str  # 管理员IP（用于审计）
    approved_by: str  # 审批人ID
    approved_ip: str  # 审批人IP
    max_position_pct: float
    created_at: datetime
    expires_at: datetime
    reason: str
    is_active: bool
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    outcome: Optional[dict] = None  # 交易结果跟踪

@dataclass
class PardonOutcome:
    """赦免交易结果"""
    pardon_id: str
    stock_code: str
    entry_price: float
    exit_price: float
    return_pct: float
    was_successful: bool
    lessons_learned: str
```

**API端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sentiment/weather/pardon/toggle` | 切换战法赦免状态（需2FA + 双人审批） |
| POST | `/api/sentiment/weather/pardon/revoke` | 手动撤销赦免（仅创建人或审批人） |
| GET | `/api/sentiment/weather/pardon/history` | 获取赦免历史记录 |
| POST | `/api/sentiment/weather/pardon/outcome` | 提交赦免交易结果（用于优化） |

**前端展示**：
- 熔断规则 Tab 新增"赦免管理"子模块
- 战法列表显示赦免开关：`[🔒 锁定] / [🔓 赦免]`
- 赦免记录表格：`战法 | 开启人 | 审批人 | 有效期 | 状态 | 操作`
- 操作日志：`管理员A 于 15:30 赦免了「首板挖掘」战法，有效期24小时`
- 结果跟踪：`✅ 成功（+5.2%）` / `❌ 失败（-3.1%）` / `⏳ 进行中`

---

#### 4.1.5.16 测试策略（更新）

1. **单元测试**：
   - 天气状态判定逻辑（边界值测试）
   - 多因子加权计算（权重归一化测试）
   - 熔断规则触发逻辑
   - **新增**：数据新鲜度校验测试
   - **新增**：A股通道滑点补偿计算测试
   - **新增**：结算买入价逻辑测试
   - **新增**：封单风险双指标校验测试
   - **新增**：赦免战法开关逻辑测试

2. **集成测试**：
   - 与 STI 引擎数据对接
   - **新增**：日内数据延迟场景模拟
   - **新增**：T+1结算规则验证
   - **新增**：封单额/流通盘动态阈值测试

3. **E2E 测试**：
   - 完整天气状态切换流程
   - 策略推荐正确性验证
   - 熔断规则触发场景测试
   - **新增**：死循环防护场景测试
   - **新增**：赦免战法操作流程测试

---

#### 4.1.5.17 监控与可观测性（更新）

1. **业务指标**：
   - 各天气状态分布占比
   - 策略推荐准确率（次日验证）
   - 熔断规则触发次数
   - **新增**：数据延迟监控（P95延迟、过期数据占比）
   - **新增**：条件单滑点实际值 vs 预估值对比
   - **新增**：封单风险触发次数（按个股/按日期）
   - **新增**：赦免战法使用频率和胜率

2. **技术指标**：
   - API 响应时间
   - 计算耗时
   - 缓存命中率
   - **新增**：死循环检测触发次数
   - **新增**：通道延迟监控

3. **日志规范**：
   - 每次天气计算记录输入参数和输出结果
   - 熔断触发记录完整上下文
   - 错误日志包含堆栈信息
   - **新增**：数据过期警告日志
   - **新增**：赦免操作审计日志（管理员ID、时间、战法、原因）

---

### 4.2 涨停基因选股器（增强）

> **文件**：`backend/limitup_screener.py`  
> **定位**：从3000+股票中筛选出具有"涨停基因"的候选标的

#### 4.2.1 五因子基因评分（保留+增强）

| 因子 | 权重 | 计算方法 | V2.0变更 |
|------|------|---------|---------|
| 次日溢价率 premium | 0.25 | Wilson区间校正次日高开概率 | 保留 |
| 红盘率 red_plate | 0.25 | 次日收红概率(Wilson校正) | 保留 |
| 封板率 seal | 0.25 | 平均封板时间(fbt)归一化 | 保留 |
| 炸板后溢价 open_premium | 0.15 | 炸板后次日表现 | 保留 |
| 涨停频次 activity | 0.10 | 近期涨停次数/回溯天数 | 保留 |

**V2.0 增强：行业对比维度（滚动60日中位数）**
```python
# 新增：行业归一化得分 — 滚动窗口避免全历史偏差
# 参考：借鉴DSA行业归一化思路，使用滚动60日中位数
INDUSTRY_NORM_WINDOW = 60  # 滚动窗口（交易日）

def calc_industry_normalized_score(raw_score: float, industry: str) -> float:
    """将基因得分在行业内归一化（滚动60日中位数基准）"""
    # 获取同行业近60日的基因得分中位数
    industry_median = get_industry_rolling_median(
        industry, window=INDUSTRY_NORM_WINDOW
    )
    if industry_median == 0:
        return 50.0  # 无数据时返回中性值
    # 相对中位数的偏离度（>100 表示优于行业中位数）
    ratio = raw_score / industry_median
    return round(ratio * 100, 1)
```

#### 4.2.2 批量历史回溯优化（大数据吞吐）

```python
# V1.6: 10天一批串行
# V2.0: 并发批量 + 增量更新
async def collect_zt_history_batch_optimized(codes: List[str], days: int = 250):
    """优化版批量回溯"""
    # 1. 增量模式：只获取上次计算后的新数据
    last_date = get_last_computed_date()
    if last_date:
        days_needed = (today - last_date).days
        if days_needed <= 1:
            return get_cached_results()  # 无新数据，直接返回
    
    # 2. 并发批量：10个一批，并发请求
    batches = [codes[i:i+10] for i in range(0, len(codes), 10)]
    results = await asyncio.gather(*[fetch_batch(batch) for batch in batches])
    
    # 3. 合并+写入缓存
    return merge_and_cache(results)
```

#### 4.2.3 并发保护与预计算

```python
# 保留V1.6的COMPUTING锁机制
_COMPUTING = {}  # {key: asyncio.Event}

async def get_or_compute(key, compute_fn):
    """并发保护：重复请求自动等待"""
    if key in _COMPUTING:
        await _COMPUTING[key].wait()
        return get_cached(key)
    
    event = asyncio.Event()
    _COMPUTING[key] = event
    try:
        result = await compute_fn()
        set_cached(key, result)
        return result
    finally:
        event.set()
        del _COMPUTING[key]
```

---

### 4.3 推荐引擎与仓位建议（新增）

> **参考**：DSA `seal_plate_analyzer.py` 推荐逻辑  
> **定位**：从基因得分生成研究式推荐，使用**教育研究式口吻**，非交易建议

#### 4.3.1 推荐等级体系

```python
class RecommendationLevel(Enum):
    """推荐等级 — 基于基因得分的教育研究式分级"""
    HIGH_QUALITY = "高质量关注"      # 基因得分 ≥ 75，行业百分位 ≥ 80
    MEDIUM_QUALITY = "中等质量关注"  # 基因得分 60-75
    LOW_QUALITY = "低质量关注"       # 基因得分 < 60
    AVOID = "策略逻辑上回避"         # 满足以下任一量化条件

# AVOID 触发条件（量化判定，避免主观判断）
AVOID_CONDITIONS = {
    "seal_break_streak": 3,         # 近3日连续炸板（≥3次炸板）
    "gene_score_decay_pct": 30,     # 基因得分连续5日衰减 ≥ 30%
    "open_premium_negative_avg": -3, # 近5日平均开盘溢价 < -3%
    "extreme_sti_phase": ["冰点"],   # STI处于冰点阶段时整体回避
}

# 仓位建议百分比（研究参考，非交易指令）
POSITION_SUGGESTIONS = {
    "高质量关注": {"研究仓位": "10-15%", "逻辑": "基因得分高，历史统计表现优秀"},
    "中等质量关注": {"研究仓位": "5-10%", "逻辑": "基因得分中等，需结合其他因素"},
    "低质量关注": {"研究仓位": "0-5%", "逻辑": "基因得分低，仅作观察"},
    "策略逻辑上回避": {"研究仓位": "0%", "逻辑": "触发AVOID量化条件，历史统计特征极差"},
}
```

#### 4.3.2 教育研究式表述规范

**所有推荐文案必须使用中性表述**：

| ❌ 禁止 | ✅ 允许 |
|---------|---------|
| "强烈推荐买入" | "从历史统计角度看，该标的基因得分较高" |
| "目标价XX元" | "基于历史溢价率分布，参考区间为XX-YY" |
| "仓位建议20%" | "策略逻辑上，研究参考仓位为10-15%" |
| "止损位XX" | "历史统计止损参考位为-7%" |
| "必涨" | "历史统计特征显示上涨概率较高" |

#### 4.3.3 推荐输出格式

```python
@dataclass
class StockRecommendation:
    code: str
    name: str
    gene_score: float           # 基因总分
    industry_normalized: float  # 行业百分位得分
    level: RecommendationLevel
    position_suggestion: str    # 研究仓位建议
    reasoning: List[str]        # 推荐理由（教育性表述）
    risk_notes: List[str]       # 风险提示
    factor_breakdown: dict      # 五因子明细
    
    def to_feishu_card(self) -> dict:
        """转换为飞书卡片格式"""
        return {
            "header": {"title": f"📊 研究关注: {self.name}({self.code})"},
            "elements": [
                {"tag": "markdown", "content": f"**基因得分**: {self.gene_score}"},
                {"tag": "markdown", "content": f"**推荐等级**: {self.level.value}"},
                {"tag": "markdown", "content": f"**研究仓位**: {self.position_suggestion}"},
                {"tag": "markdown", "content": f"**逻辑**: {'; '.join(self.reasoning)}"},
                {"tag": "markdown", "content": f"**风险**: {'; '.join(self.risk_notes)}"},
                {"tag": "note", "content": "⚠️ 历史统计特征，不代表未来行为。仅作研究参考，不构成投资建议。"},
            ]
        }
```

---

### 4.4 候选池竞价监控（重设计）

> **参考**：DSA `bidding_monitor.py` — 候选池 + 10秒采样 + 9:25一次性确认推送  
> **定位**：不做全市场监控，仅对前日推荐的候选池标的进行竞价跟踪，9:25最终确认推送

#### 4.4.1 候选池构建

```python
# 候选池：来自前日收盘后推荐引擎的 HIGH/MEDIUM 标的
# 不超过20只，避免竞价期负载过高
WATCHLIST_MAX_SIZE = 20

async def build_auction_watchlist() -> List[str]:
    """构建竞价监控候选池"""
    recommendations = await get_yesterday_recommendations()
    watchlist = [
        r.code for r in recommendations
        if r.level in [RecommendationLevel.HIGH_QUALITY, RecommendationLevel.MEDIUM_QUALITY]
    ]
    return watchlist[:WATCHLIST_MAX_SIZE]
```

#### 4.4.2 竞价信号维度

```python
@dataclass
class AuctionSignal:
    """集合竞价信号"""
    code: str
    name: str
    
    # 核心信号
    open_premium: float         # 高开幅度 (0-6% 区间)
    auction_amount: float       # 竞价成交额
    volume_ratio: float         # 量比（vs 5日平均）
    cancel_rate: float          # 撤单率 (0-100%)
    
    # 市值分层
    market_cap_tier: str        # 小盘(<50亿) / 中盘(50-200亿) / 大盘(>200亿)
    
    # 信号判定
    signal_type: str            # "爆量高开" / "缩量平开" / "异常撤单" / "无信号"
    confidence: float           # 信号置信度 (0-1)
    
    # 教育性说明
    reasoning: List[str]        # 信号解读
```

#### 4.4.3 市值分层阈值

```python
# 不同市值的竞价金额阈值（避免大盘股误判）
AUCTION_THRESHOLDS = {
    "small":  {"amount_min": 3_000_000,  "volume_ratio_min": 3.0},  # <50亿
    "mid":    {"amount_min": 10_000_000, "volume_ratio_min": 2.5},  # 50-200亿
    "large":  {"amount_min": 30_000_000, "volume_ratio_min": 2.0},  # >200亿
}
```

#### 4.4.4 候选池竞价监控流程

```python
async def monitor_auction():
    """
    候选池竞价监控（借鉴DSA bidding_monitor.py）
    - 9:15-9:25 每10秒采样候选池竞价数据
    - 9:25 最终确认，一次性推送
    - 不做全市场扫描，仅跟踪候选池
    """
    watchlist = await build_auction_watchlist()
    if not watchlist:
        return
    
    # 9:15-9:25 期间每10秒采样（批量拉取）
    for tick in range(9 * 60 + 15, 9 * 60 + 25):  # 每分钟6次
        await asyncio.sleep(10)
        snapshot = await fetch_auction_snapshot_batch(watchlist)
        update_auction_cache(snapshot)
    
    # 9:25 最终确认 — 一次性推送
    final_snapshot = await fetch_auction_snapshot_batch(watchlist)
    signals = analyze_final_auction(final_snapshot)
    
    if signals:
        # 生成飞书卡片，一次性推送
        card = build_auction_card(signals)
        await push_feishu_card(card)
```

---

### 4.5 游资席位引擎（增强）

> **文件**：`backend/seat_engine.py`  
> **定位**：追踪活跃游资席位动向，提供主力行为参考

#### 4.5.1 九大活跃游资追踪

```python
TOP_TRADERS = [
    {"name": "赵老哥",    "seats": ["银河证券绍兴营业部"],    "style": "打板接力"},
    {"name": "炒股养家",  "seats": ["华鑫证券上海宛平南路"],  "style": "首板挖掘"},
    {"name": "作手新一",  "seats": ["国泰君安上海江苏路"],    "style": "高位接力"},
    {"name": "章盟主",    "seats": ["中信证券杭州四季路"],    "style": "趋势跟踪"},
    {"name": "宁波桑田路","seats": ["光大证券宁波解放南路"],  "style": "板块轮动"},
    {"name": "成都帮",    "seats": ["国泰君安成都北一环路"],  "style": "低位首板"},
    {"name": "广州帮",    "seats": ["中泰证券广州天河东路"],  "style": "趋势+打板"},
    {"name": "欢乐海岸",  "seats": ["华泰证券深圳益田路"],    "style": "高位龙头"},
    {"name": "上海溧阳路","seats": ["中信证券上海溧阳路"],    "style": "综合风格"},
]
```

#### 4.5.2 席位标签系统

```python
@dataclass
class SeatLabel:
    trader_name: str           # 游资名称
    seat_name: str             # 席位全称
    trade_style: str           # 交易风格
    win_rate: float            # 历史胜率（简单统计）
    avg_return: float          # 平均收益率
    recent_activity: List[str] # 近30天操作记录
    confidence: float          # 标签可信度（基于样本量）
    
    # 合规标签
    disclaimer: str = "历史统计特征，不构成投资建议"
```

#### 4.5.3 席位关联分析

```python
async def analyze_seat_correlation(code: str, date: str) -> SeatAnalysis:
    """分析个股的席位关联"""
    # 1. 查询龙虎榜数据
    lhb_data = await fetch_lhb_data(code, date)
    
    # 2. 匹配已知游资席位
    matched_traders = match_seats(lhb_data, TOP_TRADERS)
    
    # 3. 计算席位信号
    signals = []
    for trader in matched_traders:
        if trader.win_rate > 0.55 and trader.confidence > 0.7:
            signals.append(f"高胜率游资 {trader.trader_name} 近期关注")
    
    return SeatAnalysis(code=code, signals=signals, traders=matched_traders)
```

---

### 4.6 每日复盘（增强）

> **文件**：`backend/daily_review.py`  
> **定位**：盘后自动生成结构化复盘报告

#### 4.6.1 复盘内容框架

```python
@dataclass
class DailyReview:
    date: str
    
    # 市场概览
    market_overview: MarketOverview    # 涨跌分布、成交额、STI状态
    
    # 板块轮动
    sector_rotation: List[SectorMove]  # 板块涨跌TOP5、轮动趋势
    
    # 情绪复盘
    emotion_review: EmotionReview      # STI变化、涨停/跌停分析、连板梯队
    
    # 个股复盘
    stock_review: List[StockReview]    # 关注标的当日表现、基因得分变化
    
    # 策略回顾
    strategy_review: StrategyReview    # 今日推荐回顾、准确率统计
    
    # 明日展望
    outlook: str                       # 基于情绪周期的教育性展望
```

#### 4.6.2 板块轮动分析

```python
@dataclass
class SectorMove:
    sector: str
    change_pct: float           # 板块涨跌幅
    stock_count: int            # 板块内股票数
    limit_up_count: int         # 涨停家数
    top_stocks: List[str]       # 板块内TOP股票
    rotation_signal: str        # "资金流入" / "资金流出" / "震荡"
    
    # 连续性判断
    consecutive_days: int       # 连续N天同方向
    trend_strength: str         # "强" / "中" / "弱"
```

---

### 4.7 个股深度页（增强）

> **路由**：`/api/stock/{code}/deep`  
> **定位**：单股票全维度研究视图

#### 4.7.1 深度页数据整合

```python
@dataclass
class StockDeepData:
    code: str
    name: str
    
    # K线数据
    kline: List[KLineBar]           # 近60日K线
    kline_pattern: str              # K线形态描述
    
    # 资金流向
    fund_flow: FundFlow             # 主力/散户资金流
    
    # 龙虎榜
    lhb_data: LhbData               # 龙虎榜席位+净买入
    
    # 基因得分
    gene_score: GeneScoreDetail     # 五因子明细
    
    # 席位分析
    seat_analysis: SeatAnalysis     # 游资席位关联
    
    # STI状态
    current_sti: STIResult          # 当前市场情绪温度
    
    # AI摘要
    ai_summary: str                 # AI生成的研究摘要（教育性）
```

---

### 4.8 AI/ML过滤引擎（🔮 未来实验方向 — 当前阶段暂不实现）

> **🔮 未来实验方向**：本模块定义了AI/ML过滤引擎的设计方案，但**当前V2.0阶段暂不实现**。将其保留在此作为未来实验的参考设计。  
> **参考**：DSA XGBoost 部分  
> **定位**：多维度ML预测，作为基因选股的辅助验证层  
> **⚠️ 实验性功能**：本模块为实验性功能，不纳入核心流程。核心流程不依赖ML过滤，ML结果仅作为可选参考叠加层。待V2.0核心模块（§4.1-4.7, §4.9-4.14）全部稳定后，再评估是否启动ML实验。

#### 4.8.1 特征工程

```python
FEATURE_COLUMNS = [
    # 量价特征 (8维)
    "volume_ratio_5d",           # 5日量比
    "price_position_20d",        # 20日价格位置 (0-1)
    "amplitude_avg_5d",          # 5日平均振幅
    "turnover_rate_5d",          # 5日平均换手率
    "high_low_ratio_5d",         # 5日高低比
    "gap_open_count_5d",         # 5日跳空次数
    "consecutive_up_days",       # 连涨天数
    "volatility_20d",            # 20日波动率
    
    # 涨停特征 (5维)
    "zt_count_30d",              # 30日涨停次数
    "avg_zt_premium",            # 平均涨停溢价
    "seal_rate_gene",            # 封板率基因得分
    "fbt_avg_30d",               # 30日平均封板时间
    "break_rate_30d",            # 30日炸板率
    
    # 资金特征 (4维)
    "main_net_inflow_5d",        # 5日主力净流入
    "north_flow_5d",             # 5日北向资金
    "lhb_net_buy_30d",           # 30日龙虎榜净买入
    "margin_balance_chg",        # 融资余额变化
    
    # 市场特征 (3维)
    "sti_current",               # 当前STI温度
    "sector_momentum",           # 板块动量
    "market_breadth",            # 市场广度
]

# 共 20 维特征
```

#### 4.8.2 模型训练与验证

```python
class MLFilterEngine:
    """XGBoost多维度ML过滤引擎"""
    
    def __init__(self):
        self.model = None
        self.feature_importance = None
    
    async def train(self, lookback_days: int = 250):
        """训练模型"""
        # 1. 获取训练数据
        X, y = await self._prepare_dataset(lookback_days)
        
        # 2. 特征标准化
        X_scaled = self.scaler.fit_transform(X)
        
        # 3. 5-fold交叉验证
        cv_scores = cross_val_score(self.model, X_scaled, y, cv=5, scoring='roc_auc')
        
        # 4. 过拟合检测：OOS < 0.6 则告警
        if cv_scores.mean() < 0.6:
            logger.warning(f"模型OOS得分偏低: {cv_scores.mean():.3f}")
        
        # 5. 训练最终模型
        self.model.fit(X_scaled, y)
        self.feature_importance = dict(zip(FEATURE_COLUMNS, self.model.feature_importances_))
    
    async def predict(self, code: str) -> AIPrediction:
        """预测单只股票"""
        features = await self._extract_features(code)
        features_scaled = self.scaler.transform([features])
        
        probability = self.model.predict_proba(features_scaled)[0][1]
        
        return AIPrediction(
            code=code,
            confidence=probability,
            top_features=self._get_top_k_features(features, k=5),
            model_version=self.model_version,
        )
```

#### 4.8.3 模型生命周期管理

```python
# 每日重训策略
MODEL_CONFIG = {
    "retrain_days": 1,           # 每日重训
    "lookback_days": 250,        # 回溯250日
    "oos_threshold": 0.6,        # OOS得分阈值
    "auto_rollback": True,       # 连续5日OOS<0.45自动回滚
    "feature_importance_min": 0.01,  # 特征重要性低于1%的移除
    "enabled": False,            # 默认关闭，手动开启
}
```

> **🔮 实验性说明**：ML过滤引擎为**未来实验方向**，当前V2.0阶段暂不实现。核心推荐流程不依赖此模块。待V2.0核心功能稳定后，若回测数据表明ML过滤确实能提升胜率≥5%，再启动实验验证。详细设计保留在本文档中作为未来参考。

---

### 4.9 信息推送系统（新增）

> **参考**：DSA `daily_feishu_notifier.py`  
> **定位**：投研信息主动推送到飞书，覆盖盘前/盘中/盘后

#### 4.9.1 推送时间表

```python
PUSH_SCHEDULE = {
    "pre_market": "09:10",       # 盘前：今日关注清单 + 竞价信号
    "auction_signal": "09:25",   # 竞价结束：最终竞价信号推送
    "intraday_alert": "continuous",  # 盘中：异常信号即时推送
    "daily_review": "15:30",     # 盘后：每日复盘报告
    "weekly_report": "Monday 18:00",  # 周报
    "monthly_report": "1st 18:00",    # 月报
}
```

#### 4.9.2 飞书卡片模板

```python
def build_daily_review_card(review: DailyReview) -> dict:
    """构建每日复盘飞书卡片"""
    return {
        "header": {
            "title": f"📊 {review.date} 投研复盘",
            "template": "blue"
        },
        "elements": [
            # STI温度
            {
                "tag": "column_set",
                "columns": [
                    {"tag": "column", "width": "weighted", "weight": 1,
                     "elements": [{"tag": "markdown", "content": f"**STI温度**: {review.sti.score} ({review.sti.phase})"}]},
                    {"tag": "column", "width": "weighted", "weight": 1,
                     "elements": [{"tag": "markdown", "content": f"**涨停数**: {review.market_overview.zt_count}"}]},
                ]
            },
            # 板块轮动
            {"tag": "markdown", "content": "**板块轮动**"},
            *[{"tag": "markdown", "content": f"  • {s.sector}: {s.change_pct:+.1f}% ({s.rotation_signal})"} 
              for s in review.sector_rotation[:5]],
            # 关注标的
            {"tag": "markdown", "content": "**今日关注**"},
            *[{"tag": "markdown", "content": f"  • {s.name}({s.code}): {s.gene_score}分 {s.recommendation_level}"}
              for s in review.stocks[:5]],
            # 免责声明
            {"tag": "note", "content": "⚠️ 以上内容为历史统计特征分析，不代表未来行为。仅作研究参考，不构成投资建议。"}
        ]
    }
```

#### 4.9.3 推送去重与分层节流

```python
# 分层节流：不同推送类型独立配额
PUSH_THROTTLE = {
    # 层级1：竞价信号（高优先级，稀缺性）
    "auction": {
        "same_ticker_interval_sec": 600,  # 同股票10分钟不重复
        "max_daily_per_ticker": 1,        # 单股每日最多1条竞价信号
        "max_daily_total": 5,             # 全局每日最多5条
    },
    # 层级2：推荐关注（中优先级）
    "recommendation": {
        "same_ticker_interval_sec": 1800, # 同股票30分钟不重复
        "max_daily_per_ticker": 2,        # 单股每日最多2条
        "max_daily_total": 10,            # 全局每日最多10条
    },
    # 层级3：复盘/席位（低优先级，批量推送）
    "review": {
        "max_daily_total": 3,             # 每日最多3条复盘
    },
    # 全局规则
    "quiet_hours": (22, 7),              # 22:00-07:00不推送
}
```

---

### 4.10 简化版回测（新增）

> **参考**：DSA 回测逻辑简化版  
> **定位**：验证基因得分的有效性，提供策略可信度参考

#### 4.10.1 回测设计

```python
@dataclass
class BacktestResult:
    """简化版回测结果"""
    period: str                    # 回测区间
    total_signals: int             # 总信号数
    hit_count: int                 # 命中数（基因得分≥60且次日上涨）
    hit_rate: float                # 命中率
    avg_return: float              # 平均收益率
    max_drawdown: float            # 最大回撤
    sharpe_ratio: float            # 夏普比率
    
    # 散点图数据
    scatter_data: List[dict]       # [{gene_score, next_day_return, code, date}]
    
    # 分位分析
    percentile_analysis: dict      # {score_range: {count, avg_return, hit_rate}}
```

#### 4.10.2 基因得分 vs 次日表现散点图

```python
async def generate_scatter_data(date_range: Tuple[str, str]) -> List[dict]:
    """生成基因得分与次日表现的散点图数据"""
    points = []
    for date in get_trading_days(date_range[0], date_range[1]):
        scores = await get_gene_scores(date)
        for score in scores:
            next_day_return = await get_next_day_return(score.code, date)
            points.append({
                "gene_score": score.total_score,
                "next_day_return": next_day_return,
                "code": score.code,
                "date": date,
                "industry": score.industry,
            })
    return points
```

---

### 4.11 战法信号系统（新增）

> **参考**：DSA `short_term_strategy.py` 8大战法  
> **定位**：为每只候选股匹配最适合的短线战法，给出具体入场价/止损/止盈/持仓天数/历史成功率

#### 4.11.1 战法库定义

```python
@dataclass
class StrategySignal:
    """战法信号（修正版 V2.0.2）"""
    strategy_name: str          # 战法名称
    strategy_code: str          # 首板挖掘/连板接力/炸板回封/低吸龙头/反包战法/N字反击/平台突破/尾盘偷袭
    entry_price: float          # 建议入场价
    stop_loss: float            # 止损价
    take_profit: float          # 止盈价
    max_hold_days: int          # 最大持仓天数
    historical_win_rate: float  # 历史成功率
    confidence: float           # 当前信号置信度 (0-1)
    conditions: dict            # 战法触发条件
    risk_reward_ratio: float    # 风险收益比
    
    # 入场逻辑
    entry_condition: str        # 入场确认条件（如"竞价量>5日平均2倍"）
    entry_type: str             # 入场类型（开盘/竞价/尾盘）
    
    # 风控逻辑
    stop_loss_condition: str    # 止损触发条件（如"跌破入场价-3%"）
    take_profit_condition: str  # 止盈触发条件（如"涨至+8%回落"）
    
    # 持仓管理
    exit_condition: str         # 主动离场条件（如"连板高度≥3板"）
    
    # 历史统计
    historical_avg_return: float # 历史平均收益率
    sample_size: int            # 统计样本量（用于置信度评估）
    
    # 教育性说明
    reasoning: List[str]        # 推荐理由（教育性表述）
    risk_notes: List[str]       # 风险提示

@dataclass
class StrategyMatch:
    """战法匹配结果"""
    stock_code: str
    stock_name: str
    matched_strategies: List[StrategySignal]  # 匹配到的战法列表
    best_strategy: StrategySignal             # 最优战法推荐
    gene_score: float                         # 关联基因得分
    sti_label: str                            # 关联STI情绪阶段
```

#### 4.11.2 八大战法定义

| 战法 | 触发条件 | 入场逻辑 | 止损规则 | 止盈规则 | 持仓天数 |
|------|---------|---------|---------|---------|---------|
| **首板挖掘** | 首次涨停+基因得分≥60+量比>1.5 | 次日竞价/开盘确认后 | 跌破前日收盘价-3% | +5%~+10% | 1-3天 |
| **连板接力** | 连板≥2+封板强度≥0.8+板块热度 | 连板次日竞价确认 | 跌破前日收盘价 | +8%~+15% | 1-2天 |
| **炸板回封** | 涨停后开板≥1次+回封+封板强度≥0.6 | 回封确认后 | 跌破回封价 | +5%~+8% | 1天 |
| **低吸龙头** | 板块龙头回调+STI非冰点+资金净流入 | 回调至5日均线附近 | 跌破10日均线 | +8%~+12% | 2-5天 |
| **反包战法** | 前日跌停/大阴线+今日放量+游资席位出现 | 尾盘确认反包 | 跌破前日最低价 | +5%~+8% | 1-2天 |
| **N字反击** | 2日内涨停→回调→再次放量 | 回调企稳后放量 | 跌破回调低点 | +5%~+10% | 2-3天 |
| **平台突破** | 横盘≥5日+今日突破+成交额放大2倍 | 突破确认后 | 跌破平台上沿 | +8%~+15% | 3-7天 |
| **尾盘偷袭** | 14:30后急拉+封板+量比>2 | 尾盘封板确认 | 跌破封板价 | +3%~+5% | 1天 |

#### 4.11.3 战法匹配引擎

```python
async def match_strategies(
    stock_code: str,
    gene_score: float,
    sti_label: str,
    market_context: dict
) -> StrategyMatch:
    """为个股匹配所有适用战法并排序"""
    matched = []
    for strategy in STRATEGY_REGISTRY:
        if await strategy.check_conditions(stock_code, market_context):
            signal = await strategy.generate_signal(stock_code, gene_score)
            matched.append(signal)
    
    # 按风险收益比排序
    matched.sort(key=lambda s: s.risk_reward_ratio * s.historical_win_rate, reverse=True)
    
    return StrategyMatch(
        stock_code=stock_code,
        matched_strategies=matched,
        best_strategy=matched[0] if matched else None,
        ...
    )
```

#### 4.11.4 API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/strategy/signals/{date}` | 获取当日所有战法信号 |
| GET | `/api/strategy/signals/{stock_code}` | 获取个股战法匹配 |
| GET | `/api/strategy/registry` | 获取战法库定义 |

---

### 4.12 胜率追踪与策略调整（新增）

> **参考**：DSA `win_rate_tracker.py`  
> **定位**：形成"推荐→跟踪→反馈→调参"闭环，持续优化推荐质量

#### 4.12.1 胜率追踪模型

```python
@dataclass
class WinRateRecord:
    """单笔交易记录"""
    stock_code: str
    stock_name: str
    strategy_used: str         # 使用的战法
    entry_date: str            # 入场日期
    entry_price: float         # 入场价
    exit_date: str             # 出场日期
    exit_price: float          # 出场价
    return_pct: float          # 收益率
    is_win: bool               # 是否盈利
    gene_score: float          # 入场时基因得分
    sti_label: str             # 入场时STI阶段
    sector: str                # 所属板块

@dataclass
class WinRateStats:
    """胜率统计"""
    window_size: int           # 滚动窗口大小 (10/20/30)
    total_trades: int          # 窗口内总交易数
    win_count: int             # 盈利次数
    win_rate: float            # 胜率
    avg_return: float          # 平均收益率
    max_drawdown: float        # 最大回撤
    sharpe_ratio: float        # 夏普比率
    trend: str                 # improving/stable/declining
    sector_breakdown: dict     # 按板块拆分胜率
    strategy_breakdown: dict   # 按战法拆分胜率
    score_breakdown: dict      # 按基因得分区间拆分胜率
```

#### 4.12.2 自动策略调整

```python
async def generate_strategy_adjustments(stats: WinRateStats) -> List[dict]:
    """根据胜率趋势自动生成策略调整建议"""
    adjustments = []
    
    if stats.trend == "declining" and stats.win_rate < 0.4:
        adjustments.append({
            "type": "reduce_exposure",
            "reason": f"胜率下降至{stats.win_rate:.1%}，建议降低仓位",
            "action": "将HIGH等级仓位从30%降至20%"
        })
    
    # 板块维度：识别弱势板块
    for sector, rate in stats.sector_breakdown.items():
        if rate < 0.3:
            adjustments.append({
                "type": "avoid_sector",
                "reason": f"{sector}板块胜率仅{rate:.1%}",
                "action": f"建议暂时回避{sector}板块"
            })
    
    # 战法维度：识别弱势战法
    for strategy, rate in stats.strategy_breakdown.items():
        if rate < 0.35:
            adjustments.append({
                "type": "disable_strategy",
                "reason": f"{strategy}战法胜率仅{rate:.1%}",
                "action": f"建议暂停使用{strategy}战法"
            })
    
    return adjustments
```

#### 4.12.3 API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/winrate/stats` | 获取胜率统计（支持window_size参数） |
| GET | `/api/winrate/trends` | 获取胜率趋势图数据 |
| GET | `/api/winrate/adjustments` | 获取策略调整建议 |
| GET | `/api/winrate/sector/{sector}` | 获取板块胜率拆分 |
| GET | `/api/winrate/strategy/{strategy}` | 获取战法胜率拆分 |

---

### 4.13 一日游风险检测（新增）

> **参考**：DSA `capital_flow_analyzer.py` + `dragon_tiger_risk.py`  
> **定位**：综合资金流+龙虎榜席位特征，识别"首日净买+次日净卖"的一日游模式

#### 4.13.1 风险评分模型

```python
@dataclass
class OneDayRisk:
    """一日游风险评估（动态版 V2.0.2）"""
    stock_code: str
    
    # 动态评分（实时更新）
    risk_score: float              # 风险评分 (0-100)，随资金流动态变化
    risk_level: str                # HIGH/MEDIUM/LOW，基于risk_score动态判定
    score_components: dict         # 各维度得分明细（用于解释）
    
    # 资金流维度（动态）
    capital_flow_signal: float     # 资金流信号 (-1 到 +1)，实时更新
    capital_flow_trend: str        # 流入/流出/震荡，基于时序判断
    big_fund_detected: bool        # 是否检测到大基金
    big_fund_type: str             # 大基金类型 (游资/机构/北向)
    fund_flow_history: List[dict]  # 近5日资金流历史（用于趋势判断）
    
    # 龙虎榜维度（半动态）
    dragon_tiger_risk: float       # 龙虎榜风险评分（T+1更新）
    one_day_seats: List[str]       # 一日游特征席位
    multi_seat_signal: bool        # 多席位同时出现信号
    seat_confidence: float         # 席位识别置信度
    
    # 综合判断
    recommendation: str            # 建议 (关注风险/谨慎参与/可正常参与)
    factors: List[str]             # 风险因素列表
    last_updated: str              # 最后更新时间（用于前端展示时效性）
    
    # 动态阈值
    dynamic_thresholds: dict       # 基于市场环境的动态阈值
```

#### 4.13.2 一日游特征席位库

```python
ONE_DAY_SEATS = {
    "已知一日游席位": [
        # 首日买入、次日卖出的高概率席位
        {"seat": "某知名游资A", "one_day_rate": 0.72, "avg_return": -2.3},
        {"seat": "某知名游资B", "one_day_rate": 0.65, "avg_return": -1.8},
        # ... 更多席位
    ],
    "多日持仓席位": [
        # 倾向于持仓多日的席位（风险较低）
        {"seat": "某机构专用", "one_day_rate": 0.15, "avg_return": +3.2},
        # ...
    ]
}
```

#### 4.13.3 综合风险评分逻辑

```
risk_score = (资金流权重 × capital_flow_signal) 
           + (席位风险权重 × dragon_tiger_risk) 
           + (一日游席位数量 × 15) 
           + (多席位信号 × 10)

风险等级:
  risk_score ≥ 70  → HIGH (建议回避)
  risk_score ≥ 40  → MEDIUM (谨慎参与)  
  risk_score < 40  → LOW (可正常参与)
```

**动态更新机制**：

```python
async def update_one_day_risk_realtime(code: str) -> OneDayRisk:
    """实时更新一日游风险评分（V2.0.2 动态化）"""
    # 1. 获取最新资金流数据（每分钟更新）
    capital_flow = await get_realtime_capital_flow(code)
    
    # 2. 计算动态风险评分
    base_score = calculate_base_risk(code)
    flow_adjustment = calculate_flow_adjustment(capital_flow)
    dynamic_score = base_score + flow_adjustment
    
    # 3. 动态阈值调整（基于STI温度）
    sti_phase = await get_current_sti_phase()
    thresholds = get_dynamic_thresholds(sti_phase)
    
    # 4. 判定风险等级
    if dynamic_score >= thresholds["high"]:
        risk_level = "HIGH"
    elif dynamic_score >= thresholds["medium"]:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    
    return OneDayRisk(
        risk_score=dynamic_score,
        risk_level=risk_level,
        last_updated=datetime.now().isoformat(),
        ...
    )
```

#### 4.13.4 API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/risk/oneday/{stock_code}` | 获取个股一日游风险评估 |
| GET | `/api/risk/oneday/list` | 获取当日高风险个股列表 |
| GET | `/api/risk/seats` | 获取一日游特征席位库 |

---

### 4.14 板块情绪分化度（新增）

> **参考**：DSA `sentiment_engine.py` 板块分化分析  
> **定位**：检测板块间情绪分化程度，避免在分化市中满仓追热点

#### 4.14.1 分化度模型

```python
@dataclass
class SectorDivergence:
    """板块情绪分化度"""
    date: str
    divergence_score: float        # 分化度评分 (0-1)
    divergence_label: str          # 一致/轻微分化/严重分化
    
    # 板块情绪分布
    sector_sentiments: dict        # {板块名: {情绪阶段, 涨停数, 跌停数, STI值}}
    hot_sectors: List[str]         # 热门板块
    cold_sectors: List[str]        # 冷门板块
    
    # 分化特征
    concentration_ratio: float     # 涨停集中度 (前3板块占比)
    rotation_speed: float          # 板块轮动速度
    rotation_signal: str           # 加速轮动/正常轮动/板块固化
    
    # 策略建议
    strategy_advice: str           # 分化市策略建议
```

#### 4.14.2 分化度计算

```python
async def calculate_sector_divergence(date: str) -> SectorDivergence:
    """计算板块情绪分化度"""
    sector_sti = await get_sector_sti_values(date)
    
    # 1. 计算STI标准差（分化度核心指标）
    sti_values = [s["sti_value"] for s in sector_sti.values()]
    sti_std = np.std(sti_values)
    sti_range = max(sti_values) - min(sti_values)
    
    # 2. 涨停集中度
    total_limitup = sum(s["limitup_count"] for s in sector_sti.values())
    top3_sectors = sorted(sector_sti.items(), key=lambda x: x[1]["limitup_count"], reverse=True)[:3]
    concentration = sum(s[1]["limitup_count"] for s in top3_sectors) / max(total_limitup, 1)
    
    # 3. 分化度综合评分
    divergence_score = normalize(sti_std * 0.5 + sti_range * 0.3 + (1 - concentration) * 0.2)
    
    # 4. 分化等级
    if divergence_score >= 0.7:
        label = "严重分化"
        advice = "板块分化严重，建议精选个股，避免追高冷门板块"
    elif divergence_score >= 0.4:
        label = "轻微分化"
        advice = "板块有分化，建议关注热门板块龙头"
    else:
        label = "一致"
        advice = "板块情绪一致，可积极参与"
    
    return SectorDivergence(...)
```

#### 4.14.3 板块轮动速度监控

```python
async def calculate_rotation_speed(date: str, lookback_days: int = 5) -> float:
    """计算板块轮动速度（近N日热门板块变化率）"""
    recent_hot_sectors = []
    for i in range(lookback_days):
        day = get_trading_day(date, -i)
        hot = await get_hot_sectors(day, top_n=5)
        recent_hot_sectors.append(set(hot))
    
    # Jaccard距离：板块变化越大，轮动越快
    changes = []
    for i in range(len(recent_hot_sectors) - 1):
        intersection = recent_hot_sectors[i] & recent_hot_sectors[i+1]
        union = recent_hot_sectors[i] | recent_hot_sectors[i+1]
        jaccard = len(intersection) / max(len(union), 1)
        changes.append(1 - jaccard)
    
    return np.mean(changes)  # 0=固化, 1=剧烈轮动
```

#### 4.14.4 API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sector/divergence/{date}` | 获取板块情绪分化度 |
| GET | `/api/sector/divergence/history` | 获取分化度历史趋势 |
| GET | `/api/sector/rotation` | 获取板块轮动速度 |

---

## 5. 架构设计

### 5.1 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    Vibe-Research 投研助手                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │ React 19 │  │   Vite   │  │ Tailwind │  │ ECharts│ │
│  │ 前端应用  │  │ 构建工具  │  │   CSS    │  │  图表   │ │
│  └────┬─────┘  └──────────┘  └──────────┘  └────────┘ │
│       │                                                  │
│  ─────┼───── HTTP API ({"data": ...}) ──────────────────│
│       │                                                  │
│  ┌────┴─────────────────────────────────────────────┐  │
│  │                FastAPI 后端 (app.py)               │  │
│  ├─────────┬──────────┬──────────┬──────────────────┤  │
│  │ STI引擎 │ 基因选股  │ 推荐引擎  │   席位引擎       │  │
│  │增强模块  │增强模块   │  新增    │    增强模块      │  │
│  ├─────────┼──────────┼──────────┼──────────────────┤  │
│  │候选池监控│ ML过滤   │  复盘    │   个股深度        │  │
│  │ 重设计  │ (未来)   │  增强    │    增强           │  │
│  ├─────────┴──────────┴──────────┴──────────────────┤  │
│  │            推送系统 (飞书/企微) — 新增              │  │
│  ├──────────────────────────────────────────────────┤  │
│  │            回测引擎 (简化版) — 新增                │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     │                                   │
│  ┌──────────────────┴───────────────────────────────┐  │
│  │              数据层 (astock.py)                    │  │
│  │  东财HTTP API + 本地SQLite缓存 + 预计算调度       │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 5.2 数据流

```
15:30 收盘 → 预计算触发 → 数据获取(并发) → 基因评分 → STI计算 → 推荐引擎
  ↓                                                              ↓
SQLite 缓存                                                 飞书推送(15:30)
  ↓                                                              ↓
API 查询 ← 前端展示                                        盘前推送(09:10)
                                                                    ↓
候选池竞价监控(09:15-09:25) → 9:25一次性确认推送
                                                                    ↓
                                                               ML过滤(未来实验方向，当前暂不实现)
```

### 5.3 目录结构

```
backend/
├── app.py                    # FastAPI 主路由
├── astock.py                 # 东财数据层
├── limitup_screener.py       # 基因选股器 (增强)
├── limitup_sti.py            # STI情绪引擎 (增强)
├── auction_screener.py       # 竞价分析 (增强)
├── seat_engine.py            # 席位引擎 (增强)
├── daily_review.py           # 每日复盘 (增强)
├── limitup_strategy.py       # 策略展示
├── recommendation_engine.py  # 推荐引擎 (新增)
├── bidding_monitor.py        # 竞价监控 (新增)
├── ml_filter.py              # ML过滤引擎 (新增)
├── feishu_notifier.py        # 飞书推送 (新增)
├── backtest_lite.py          # 简化回测 (新增)
├── config.py                 # 配置管理
├── health.py                 # 健康检查 (新增)
└── models.py                 # 数据模型

frontend/src/
├── pages/
│   ├── LimitUpStrategy.tsx   # 打板策略页 (增强)
│   ├── DailyReview.tsx       # 复盘页 (增强)
│   ├── StockDeep.tsx         # 个股深度 (增强)
│   └── Recommendation.tsx    # 推荐页 (新增)
├── components/
│   └── charts/
│       └── KLineChart.tsx    # K线图
└── lib/
    └── api.ts                # API客户端
```

---

## 6. API 设计

### 6.1 已有端点（保留）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/limitup/screener?date=YYYY-MM-DD` | GET | 全市场基因得分清单 |
| `/api/limitup/analysis/{code}?date=YYYY-MM-DD` | GET | 个股策略分析 |
| `/api/market/sti?date=YYYY-MM-DD` | GET | STI情绪温度 |
| `/api/market/sti/timeline?days=30` | GET | STI时间线 |
| `/api/auction/today?date=YYYY-MM-DD` | GET | 竞价分析结果 |
| `/api/seat/top-traders` | GET | 9大游资列表 |
| `/api/seat/analysis/{code}?date=YYYY-MM-DD` | GET | 席位关联分析 |
| `/api/review/daily?date=YYYY-MM-DD` | GET | 每日复盘 |
| `/api/stock/{code}/deep` | GET | 个股深度数据 |

### 6.2 新增端点

| 端点 | 方法 | 说明 | V2.0新增 |
|------|------|------|---------|
| `/api/recommendation/today` | GET | 今日推荐清单 | ✅ |
| `/api/recommendation/{code}` | GET | 个股推荐详情 | ✅ |
| `/api/auction/monitor?tickers=xxx` | GET | 竞价实时监控 | ✅ |
| `/api/ml/prediction/{code}` | GET | ML预测结果 | ✅ |
| `/api/ml/model/status` | GET | 模型状态 | ✅ |
| `/api/backtest/scatter?start=&end=` | GET | 回测散点数据 | ✅ |
| `/api/backtest/result?start=&end=` | GET | 回测结果 | ✅ |
| `/api/health` | GET | 系统健康检查 | ✅ |
| `/api/push/test` | POST | 测试推送连接 | ✅ |

---

## 7. 配置系统

### 7.1 默认配置

```python
class AssistantDefaultConfig:
    """投研助手默认配置"""
    
    # === 基因选股 ===
    GENE_LOOKBACK_DAYS = 250
    GENE_QUALIFY_THRESHOLD = 60
    GENE_HIGH_THRESHOLD = 75
    GENE_FACTORS_WEIGHT = {
        "premium": 0.25,
        "red_plate": 0.25,
        "seal": 0.25,
        "open_premium": 0.15,
        "activity": 0.10,
    }
    
    # === STI情绪 ===
    STI_WEIGHTS = {
        "seal_rate": 0.25,
        "limit_up_count": 0.15,
        "up_down_ratio": 0.12,
        "prev_zt_performance": 0.12,
        "avg_premium": 0.10,
        "board_height": 0.10,
        "north_flow": 0.08,
        "turnover": 0.08,
    }
    STI_PERCENTILE_WINDOW = 252
    
    # === 推荐引擎 ===
    RECOMMEND_HIGH_THRESHOLD = 75
    RECOMMEND_MEDIUM_THRESHOLD = 60
    RECOMMEND_INDUSTRY_PERCENTILE_MIN = 80
    
    # === 竞价监控 ===
    AUCTION_OPEN_RANGE = (0.0, 0.06)
    AUCTION_VOLUME_RATIO_MIN = 3.0
    AUCTION_CANCEL_RATE_MAX = 0.25
    AUCTION_SAMPLE_INTERVAL = 30  # 秒
    
    # === ML过滤 ===
    AI_CONFIDENCE_THRESHOLD = 0.60
    AI_RETRAIN_DAYS = 1
    AI_OOS_THRESHOLD = 0.6
    AI_AUTO_ROLLBACK_DAYS = 5
    
    # === 推送 ===
    PUSH_CHANNELS = ["feishu"]
    PUSH_THROTTLE = {
        "same_ticker_interval_sec": 300,
        "max_daily_per_ticker": 3,
        "max_daily_total": 20,
    }
    
    # === 回测 ===
    BACKTEST_INITIAL_CAPITAL = 1_000_000
    BACKTEST_LOOKBACK_DAYS = 250
    
    # === 性能 ===
    CONCURRENT_REQUESTS = 10
    BATCH_SIZE = 100
    CACHE_TTL_HOURS = 12
```

### 7.2 用户配置层

```python
class AssistantUserConfig:
    """用户可覆盖的配置"""
    
    # 所有阈值类参数支持 .env 覆盖
    gene_qualify_threshold: float = None
    gene_high_threshold: float = None
    hard_stop_loss: float = None
    ai_confidence_threshold: float = None
    feishu_webhook: str = None
    
    def resolve(self, defaults: AssistantDefaultConfig) -> dict:
        """合并默认配置和用户配置"""
        config = {}
        for key, default_val in vars(defaults).items():
            user_val = getattr(self, key, None)
            config[key] = user_val if user_val is not None else default_val
        return config
```

---

## 8. 非功能需求

### 8.1 性能（三维度升级-吞吐）

#### 8.1.1 性能三层拆分模型

V2.0 采用三层拆分模型，将全市场分析耗时分解为三个独立层次，便于针对性优化和瓶颈定位：

| 层次 | 目标耗时 | 核心组件 | 优化措施 |
|------|---------|---------|---------|
| **第一层：数据获取层** | <8秒 | HTTP批量请求、增量解析、TTL缓存 | `asyncio.gather` 并发 + 增量更新 + 本地SQLite兜底 |
| **第二层：计算层** | <60秒 | 五因子评分、STI九维加权、推荐引擎、风险评估 | 并行计算 + 预计算调度 + 内存优化 |
| **第三层：展示层** | <500ms | 数据库查询、序列化、HTTP传输 | 数据库索引 + Pydantic缓存 + HTTP/2 + gzip |

**三层协同目标**：数据获取<8s + 计算<60s + 展示<500ms = **全市场分析<3分钟**

#### 8.1.2 性能指标总表

| 指标 | V1.6目标 | V2.0目标 | 分层目标 | 改进措施 |
|------|---------|---------|---------|---------|
| 全市场分析耗时 | <5分钟 | **<3分钟** | 数据获取<8s + 计算<60s + 展示<500ms | 并发获取+增量计算 |
| 竞价分析延迟 | <3秒 | **<2秒** | 展示层<500ms | 预计算+缓存 |
| 实时轮询间隔 | 5秒 | **3秒** | — | 异步优化 |
| 内存占用 | <500MB | **<300MB** | — | 分批处理 |
| API响应时间 | <1秒 | **<500ms** | 展示层<500ms | 数据库索引+缓存 |
| 首屏加载时间 | — | **<2秒** | — | 代码分割+懒加载 |

### 8.2 可靠性（三维度升级-异常边界）

| 要求 | V1.6措施 | V2.0增强措施 |
|------|---------|-------------|
| 数据异常 | 降级到上一交易日 | **多源冗余 + 本地缓存兜底 + 健康检查** |
| 网络中断 | 重试3次+指数退避 | **熔断器模式 + 自动切换备用源** |
| 模型失效 | 5日OOS<45%告警 | **自动回滚 + 飞书告警 + 人工确认** |
| 系统崩溃 | 进程守护 | **systemd + 自动重启 + 健康检查端点** |
| 极端行情 | — | **动态阈值 + 异常值过滤 + 涨停潮/跌停潮检测** |
| 配置错误 | — | **启动时配置校验 + 详细错误提示** |

### 8.3 安全性

| 要求 | 措施 |
|------|------|
| 资金安全 | **默认"生成建议+用户确认"模式，禁止自动下单** |
| 合规声明 | 所有推送消息附带免责声明 |
| 数据隐私 | 本地SQLite存储，不上传任何交易数据 |
| 模型安全 | XGBoost模型文件签名验证，防止篡改 |
| Webhook安全 | 飞书Webhook URL仅在.env中配置，不暴露 |

### 8.4 可观测性（新增）

| 要求 | 措施 |
|------|------|
| 健康检查 | `/api/health` 端点，检查数据库/API/模型状态 |
| 日志 | 结构化日志，覆盖信号/决策/推送/异常 |
| 指标 | 关键操作耗时统计（数据获取/计算/推送） |
| 告警 | 异常自动推送到飞书告警群 |
| 性能监控 | `/api/metrics/data_fetch`、`/api/metrics/compute`、`/api/metrics/api_response`、`/api/metrics/breakdown` |

---

## 9. 合规验证

### 9.1 合规基线（延续V1.6）

| 要求 | 状态 | 验证方式 |
|------|------|---------|
| 零标的红线 | ✅ | 无"排板/扫板/回避"等行动建议标签 |
| 教育性展示 | ✅ | 所有文字使用"策略逻辑上""历史统计特征"等中性表述 |
| 免责声明 | ✅ | 页面底部+API返回+飞书推送均包含 |
| 数据溯源 | ✅ | 所有数据标注来源（东财涨停板四池） |
| 游资标签合规 | ✅ | 席位标注"历史统计特征，不构成投资建议" |

### 9.2 V2.0 新增合规要求

| 要求 | 措施 |
|------|------|
| 推荐引擎合规 | 推荐等级使用"关注"而非"买入"，仓位建议标注"研究参考" |
| ML预测合规 | AI预测结果标注"模型输出，仅供参考"，置信度 <60% 不展示 |
| 竞价监控合规 | 竞价信号标注"历史统计特征，不构成交易建议" |
| 推送合规 | 飞书推送每条消息附带免责声明 |
| 回测合规 | 回测结果标注"历史回测，不代表未来表现" |
| 隐私合规 | 飞书Webhook URL不日志，不存储在非.env位置 |

---

## 10. 实施路线图

### Phase 1：核心骨架重构（3周）

> ⚠️ V2.0 更新：因纳入DSA战法系统+胜率追踪，Phase 1延长1周

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 路由架构重构 | `routers/` 目录拆分（limitup、market、portfolio、review、seat、stock、radar、myreports、watchlist、chat、health），app.py <200行 | P0 |
| 项目结构调整 | 新增 `strategy_signals.py`, `win_rate_tracker.py`, `one_day_risk.py`, `sector_divergence.py`, `recommendation_engine.py`, `bidding_monitor.py`, `feishu_notifier.py`, `backtest_lite.py`, `health.py` | P0 |
| 配置系统重构 | `config.py` 支持新增模块配置 | P0 |
| 数据模型更新 | `models.py` 新增推荐/回测/战法/胜率模型 | P0 |
| 健康检查端点 | `/api/health` | P1 |

### Phase 2：效率提升（3周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 推荐引擎实现 | 基因得分→推荐等级→仓位建议 | P0 |
| 战法信号系统 | 8大战法匹配+入场价/止损/止盈 | P0 |
| 胜率追踪系统 | 滚动胜率+板块/战法拆分+自动调参 | P0 |
| 候选池竞价监控 | 候选池+10秒采样+9:25一次性确认 | P0 |
| 飞书推送实现 | 盘前/竞价/复盘三时段推送 | P0 |
| 每日复盘增强 | 板块轮动+情绪复盘 | P1 |
| 个股深度增强 | 整合席位+推荐 | P1 |
| 推荐页前端 | `Recommendation.tsx` | P0 |
| 战法信号页前端 | `StrategySignals.tsx` | P0 |

### Phase 3：吞吐优化 + 风控增强（2周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 并发数据获取 | `asyncio.gather` 批量并发 | P0 |
| 增量计算优化 | 避免全量重算 | P0 |
| 一日游风险检测 | 资金流+龙虎榜综合评分 | P0 |
| 板块情绪分化度 | 分化度计算+轮动速度监控 | P1 |
| 预计算调度增强 | 定时任务+缓存策略 | P1 |
| 数据库索引 | 关键查询添加索引 | P1 |
| 风控模块前端 | `RiskDashboard.tsx` | P1 |

### Phase 4：异常边界 + ML实验（2周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 熔断器模式 | 数据源故障时fail-fast | P0 |
| 多源降级 | 东财故障时本地缓存兜底 | P0 |
| 极端行情检测 | 涨停潮/跌停潮动态阈值 | P1 |
| 简化版回测 | 基因得分vs次日表现散点图 | P2 |
| ~~ML过滤实验~~ | ~~XGBoost训练+OOS验证~~ | ~~移至V2.1+，作为未来实验方向~~ |

### Phase 5：打磨上线（1周）

| 任务 | 产出 | 优先级 |
|------|------|--------|
| E2E测试 | 端到端集成测试 | P0 |
| 性能测试 | 全市场分析<3分钟验证 | P0 |
| 合规审查 | 所有推送附带免责声明 | P0 |
| 文档更新 | 部署文档+API文档 | P1 |
| Docker构建 | 一键部署脚本 | P1 |

---

## 11. 核心原则

> 以下原则贯穿 V2.0 全部设计与实现，任何偏离需经审查确认。

| # | 原则 | 说明 |
|---|------|------|
| 1 | **只读不写** | 所有模块只读取数据，不向券商/交易系统写入任何指令 |
| 2 | **被动优先** | 默认被动查询模式，推送功能需用户主动开启 |
| 3 | **渐进增强** | Phase 1→5 逐步增强，每阶段独立可用 |
| 4 | **独立容错** | 各模块独立异常处理，一个模块失败不阻塞其他模块 |
| 5 | **零标的红线** | 不输出"买入/卖出/持有"等交易指令，所有建议使用教育研究式口吻 |
| 6 | **合规隔离** | 推荐/预测/竞价信号与客观数据之间增加视觉分隔 |
| 7 | **教育性展示** | 所有文字使用"策略逻辑上""历史统计特征"等中性表述 |
| 8 | **数据溯源** | 所有数据标注来源（东财/龙虎榜/北向资金） |
| 9 | **预计算优先** | 盘后预计算，API只读缓存，避免实时计算阻塞 |
| 10 | **限流遵守** | 对齐东财API限流约定（`time.sleep(1.2)`），防止IP封禁 |
| 11 | **缓存友好** | TTL缓存+并发锁+增量更新，减少重复计算 |
| 12 | **前后端解耦** | API返回`{"data": ...}`，前端`request<T>()`自动解包 |
| 13 | **最小权限** | 模块只访问必要数据，不越权读取其他模块数据 |
| 14 | **可测试性** | 每个模块独立可测试，支持mock数据源 |

---

## 13. 未来实验方向

> 以下功能已设计完整方案，但**当前V2.0阶段暂不实现**。保留设计文档供未来评估启动。

### 13.1 AI/ML过滤引擎（§4.8）

**设计保留**：完整的特征工程方案（20维）、XGBoost训练流程、OOS验证机制、模型生命周期管理——详见§4.8。

**启动条件**：
1. V2.0核心模块（§4.1-4.7, §4.9-4.14）全部稳定运行≥30个交易日
2. 积累足够的历史推荐数据（≥500条推荐记录）
3. 通过回测验证：ML过滤确实能将推荐胜率提升≥5个百分点

**预期投入**：2-3周（特征工程+训练+OOS验证+AB测试框架）

**风险**：
- 过拟合风险高（5-fold CV + OOS监控 + 自动回滚可缓解）
- 特征数据依赖东财API的稳定性和数据质量
- 模型需要每日重训，增加系统复杂度

### 13.2 高级回测引擎

**设计方向**：基于§4.10简化版回测的扩展，支持：
- 分滑点模型（扫板 vs 排板）
- 多策略组合回测
- 样本外验证 + 蒙特卡洛模拟

**启动条件**：简化版回测（§4.10）稳定运行≥3个月

### 13.3 策略插件系统

**设计方向**：当前8大战法硬编码实现。未来可扩展为插件系统，支持：
- 用户自定义战法条件
- 社区共享策略模板
- 策略参数自动优化

**启动条件**：用户反馈明确需要自定义战法

---

## 14. 附录

### 14.1 V1.6 → V2.0 模块映射

| V1.6模块 | V2.0模块 | 变更类型 | 说明 |
|----------|---------|---------|------|
| `limitup_screener.py` | §4.2 基因选股器 | 增强 | 新增行业对比维度 |
| `limitup_sti.py` | §4.1 STI引擎 | 增强 | 新增环比趋势+异常熔断 |
| `auction_screener.py` | §4.4 竞价监控 | 增强 | 新增实时监控+市值分层 |
| `seat_engine.py` | §4.5 席位引擎 | 增强 | 新增9大游资详细追踪 |
| `daily_review.py` | §4.6 每日复盘 | 增强 | 新增板块轮动+情绪复盘 |
| — | §4.3 推荐引擎 | **新增** | 基因得分→推荐等级→仓位建议 |
| — | §4.8 ML过滤 | **🔮 未来方向** | XGBoost多维度预测（当前阶段暂不实现，详见§13） |
| — | §4.9 信息推送 | **新增** | 飞书主动推送 |
| — | §4.10 简化回测 | **新增** | 基因vs次日散点图 |
| `short_term_strategy.py` | §4.11 战法信号系统 | **新增** | 8大战法+入场价/止损/止盈 |
| `win_rate_tracker.py` | §4.12 胜率追踪 | **新增** | 滚动胜率+板块拆分+自动调参 |
| `capital_flow_analyzer.py` + `dragon_tiger_risk.py` | §4.13 一日游风险 | **新增** | 资金流+席位综合风险评分 |
| `sentiment_engine.py` (板块分化部分) | §4.14 板块分化度 | **新增** | 分化度+轮动速度 |

### 14.2 技术风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 集合竞价数据延迟 | 错过入场时机 | 中 | 本地缓存+快速分析管线 |
| ~~XGBoost过拟合~~ | ~~虚高回测胜率~~ | ~~高~~ | ~~已移至未来实验方向（§13），当前阶段不涉及~~ |
| 策略拥挤导致Alpha衰减 | 胜率逐年下降 | 中 | 季度参数重校准+多策略并行 |
| 滑点和冲击成本 | 回测vs实盘差距大 | 高 | 回测区分扫板/排板滑点 |
| 东财接口变更 | 数据获取失败 | 中 | 多数据源冗余+接口健康检查 |
| 通知轰炸 | 用户疲劳/忽略 | 中 | 信号去重+每日上限+静默时段 |
| 飞书Webhook失效 | 推送失败 | 低 | 重试+本地日志兜底+告警 |

### 14.3 成功标准

| 维度 | 指标 | 目标 |
|------|------|------|
| 效率 | 研究员日均手动操作时间 | 减少 2+ 小时 |
| 吞吐 | 全市场分析耗时 | <3 分钟 |
| 可靠 | 系统可用率 | >99.5% |
| 策略 | 基因选股命中率 | >50% |
| 推送 | 飞书推送送达率 | >99% |
| ML | AI过滤器OOS AUC | >0.6（🔮 未来方向，V2.1+） |

---

> **免责声明**：本PRD所涉及的所有策略逻辑、基因评分、推荐等级等，均为基于历史数据的统计特征分析，不代表未来行为。仅作研究参考，不构成投资建议。实际交易决策需用户独立判断并自行承担风险。
