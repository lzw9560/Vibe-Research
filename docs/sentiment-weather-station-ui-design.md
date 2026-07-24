# 情绪气象站 UI 设计文档

> 版本: V2.0.3 · 2026-07-23
> 状态: 设计稿（已更新）
> 作者: Orchestrator + @designer
> 模块: Vibe-Research 市场概览子模块

---

## 一、设计目标

### 1.1 核心定位

情绪气象站是 Vibe-Research 的**市场情绪可视化中枢**，将抽象的 STI 情绪温度、风险指标、板块持续性、资金动量、舆情数据，转化为直观的**天气隐喻界面**，帮助用户快速判断当前市场环境并自动匹配最佳打板策略。

### 1.2 设计原则

1. **数据优先**：所有视觉元素服务于数据解读，不添加装饰性噪音
2. **即时可读**：3 秒内识别当前市场天气状态
3. **渐进披露**：概览层 → 详情层 → 操作层，避免信息过载
4. **一致性**：复用现有 Glass-morphism 设计系统
5. **合规性**：所有数据标注「历史统计特征，非投资建议」

---

## 二、页面布局架构

### 2.1 整体结构

```
┌─────────────────────────────────────────────────────────────┐
│  Layout (Sidebar + Main Content)                             │
│  ┌──────────┐  ┌──────────────────────────────────────────┐ │
│  │ Sidebar  │  │  SentimentWeather Page                   │ │
│  │          │  │  ┌────────────────────────────────────┐  │ │
│  │ 市场概览 │  │  │ PageHeader (标题 + 副标题 + 刷新)   │  │ │
│  │  - 每日复盘│  │  └────────────────────────────────────┘  │ │
│  │  - 情绪气象│  │  ┌────────────────────────────────────┐  │ │
│  │  - 资讯雷达│  │  │ WeatherHero (天气状态大卡片)        │  │ │
│  │  - 板块中心│  │  │ [暴风雨/阴天/晴天/极端反弹]         │  │ │
│  │  - 行业排行│  │  │ STI 温度计 + 情绪指数 + 置信度      │  │ │
│  │          │  │  └────────────────────────────────────┘  │ │
│  │ 个股分析 │  │  ┌────────────────────────────────────┐  │ │
│  │ 投资管理 │  │  │ SecondaryTabs (二级导航)            │  │ │
│  │ 打板策略 │  │  │ [实时天气] [历史趋势] [策略建议] [熔断规则] │  │ │
│  │          │  │  └────────────────────────────────────┘  │ │
│  │          │  │  ┌────────────────────────────────────┐  │ │
│  │          │  │  │ TabContent (动态内容区)             │  │ │
│  │          │  │  │                                    │  │ │
│  │          │  │  │  [根据选中 Tab 渲染不同内容]        │  │ │
│  │          │  │  │                                    │  │ │
│  │          │  │  └────────────────────────────────────┘  │ │
│  │          │  │  ┌────────────────────────────────────┐  │ │
│  │          │  │  │ Disclaimer (合规声明)               │  │ │
│  │          │  │  └────────────────────────────────────┘  │ │
│  └──────────┘  └──────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 路由结构

```tsx
// frontend/src/router.tsx
{ path: "/sentiment/weather", element: <SentimentWeather /> },
{ path: "/sentiment/weather/history", element: <SentimentWeatherHistory /> },
{ path: "/sentiment/weather/strategy", element: <SentimentWeatherStrategy /> },
{ path: "/sentiment/weather/fuse", element: <SentimentWeatherFuse /> },
```

### 2.3 侧边栏配置

```tsx
// frontend/src/components/layout/Layout.tsx
{
  name: "市场概览",
  icon: Activity,
  tabs: [
    { to: "/daily-review", label: "每日复盘" },
    { to: "/sentiment/weather", label: "情绪气象" },  // ← 新增
    { to: "/news-radar", label: "资讯雷达" },
    { to: "/sectors", label: "板块中心" },
    { to: "/industries", label: "行业排行" },
  ],
}
```

### 2.4 二级导航栏

在 `Layout.tsx` 的 secondary tab bar 条件中添加：

```tsx
{(pathname === "/sentiment/weather" || pathname.startsWith("/sentiment/weather")) && (
  <div className="border-b border-white/10 bg-black/20">
    <div className="flex gap-1 px-4">
      <NavLink to="/sentiment/weather" className="...">实时天气</NavLink>
      <NavLink to="/sentiment/weather/history" className="...">历史趋势</NavLink>
      <NavLink to="/sentiment/weather/strategy" className="...">策略建议</NavLink>
      <NavLink to="/sentiment/weather/fuse" className="...">熔断规则</NavLink>
    </div>
  </div>
)}
```

---

## 三、核心组件设计

### 3.1 WeatherHero (天气状态大卡片)

**职责**：展示当前市场天气状态、STI 温度计、情绪指数、置信度

**布局**：
```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                                                     │   │
│   │   ⛈️ 暴风雨                                          │   │
│   │   退潮期 · 建议空仓                                   │   │
│   │                                                     │   │
│   │   ┌─────────────────────────────────────────────┐   │   │
│   │   │  STI 温度计                                  │   │   │
│   │   │  ████████████░░░░░░░░░░  32°C               │   │   │
│   │   │  [冰点 ←──────────────→ 高潮]                │   │   │
│   │   └─────────────────────────────────────────────┘   │   │
│   │                                                     │   │
│   │   情绪指数: 32/100                                   │   │
│   │   置信度: 高 (数据完整度 95%)                        │   │
│   │   更新时间: 2026-07-23 15:05                         │   │
│   │                                                     │   │
│   │   [查看详细分析] [切换策略模式]                       │   │
│   │                                                     │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件接口**：
```tsx
interface WeatherHeroProps {
  weatherState: WeatherState;  // "暴风雨" | "阴天" | "晴天" | "极端反弹"
  stiScore: number | null;     // 0-100
  stiPhase: string | null;     // "高潮" | "启动" | "分歧" | "冰点" | "退潮"
  confidence: string;          // "高" | "中" | "低"
  dataUpdated: string | null;
  dataFreshness: {
    isStale: boolean;
    delayMs: number;
    lastTriggerCount: number;  // 死循环检测：单票单日触发次数
  };
  executionParams?: {
    channelLatencyMs: number;
    slippageCompensation: number;
    settlementBuyPrice: number;
    nextDaySellBase: number;
    t1Locked: boolean;
  };
  onViewDetails: () => void;
  onSwitchStrategy: () => void;
}
```

**新增数据展示区**：
```
┌─────────────────────────────────────────────────────────────┐
│  数据状态: 🟢 正常 (延迟2秒)                                  │
│  死循环检测: 今日触发 1/3 次                                  │
│  通道延迟: 200ms | 滑点补偿: ±0.1%                           │
│  预估买入价: ¥10.05 (竞价) | 次日卖出基准: ¥10.08            │
│  ⚠️ T+1锁定：当日买入不可卖出                                 │
└─────────────────────────────────────────────────────────────┘
```

**交互行为**：
- **加载状态**：显示 Skeleton 占位， shimmer 动画
- **数据更新**：数字滚动动画（可选），背景渐变过渡 500ms
- **按钮交互**：hover 时 lift 效果 `hover:-translate-y-0.5`，active 时按下效果
- **错误状态**：显示错误提示 + 重试按钮
- **空状态**：当数据缺失时，显示"数据暂未更新" + 最后可用时间
- **过期数据**：当 `dataFreshness.isStale = true` 时，显示黄色警告条 + 禁用条件单触发按钮
- **死循环警告**：当 `lastTriggerCount >= 3` 时，显示红色警告 + 自动锁定提示

**视觉规范**：
- **暴风雨**：深灰蓝渐变背景 `bg-gradient-to-br from-gray-900 to-blue-900`，红色警示图标
- **阴天**：浅灰蓝渐变 `bg-gradient-to-br from-gray-100 to-blue-100`，云朵图标
- **晴天**：暖橙渐变 `bg-gradient-to-br from-orange-100 to-yellow-100`，太阳图标
- **极端反弹**：紫红渐变 `bg-gradient-to-br from-purple-100 to-pink-100`，闪电图标

**STI 温度计**：
- 使用 ECharts gauge 组件或自定义 div 实现
- 温度范围：0°C (冰点) → 100°C (高潮)
- 颜色映射：蓝色(冷) → 绿色(温和) → 橙色(热) → 红色(极热)
- 刻度标签：冰点 / 启动 / 分歧 / 高潮
- 动画：数值变化时平滑过渡 300ms

**响应式行为**：
- **桌面端 (>1024px)**：横向布局，左侧天气状态，右侧 STI 温度计
- **平板端 (768px-1024px)**：纵向堆叠，温度计居中
- **移动端 (<768px)**：全宽显示，字体缩小 20%，按钮堆叠

**无障碍**：
- 天气状态使用 `aria-live="polite"` 实时播报
- STI 温度计使用 `role="img"` + `aria-label` 描述
- 按钮支持键盘导航，Enter/Space 激活

### 3.2 MultiFactorBreakdown (多因子分解卡片)

**职责**：展示 5 个因子的加权评分和贡献度

**布局**：
```
┌─────────────────────────────────────────────────────────────┐
│  多因子情绪分解                                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  STI 情绪温度          ████████████░░░░░░░░░░  40%          │
│  风险指标              ████████░░░░░░░░░░░░░░  20%          │
│  板块持续性            ███████████░░░░░░░░░░░  25%          │
│  资金动量              ██████░░░░░░░░░░░░░░░░  10%          │
│  舆情情绪              ████░░░░░░░░░░░░░░░░░░   5%          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  综合评分: 68/100 → 晴天 (阴天)                      │   │
│  │  主要驱动: 板块持续性强势，资金动量转正                │   │
│  │  风险提示: 炸板率偏高，注意分化                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件接口**：
```tsx
interface FactorScore {
  name: string;
  score: number;      // 0-100
  weight: number;     // 0-1
  trend: "up" | "down" | "stable";
  explanation: string;
}

interface AuctionMetric {
  name: string;
  value: number;
  unit: string;
  thresholdHigh: number;
  thresholdLow: number;
  isWarning: boolean;
}

interface SealRiskMetric {
  stockCode: string;
  sealAmount: number;        // 封单额（元）
  floatShares: number;       // 流通盘（股）
  sealRatio: number;         // 封单比例
  minRatioRequired: number;  // 最低要求比例
  riskLevel: "low" | "high";
}

interface MultiFactorBreakdownProps {
  factors: FactorScore[];
  compositeScore: number;
  weatherState: string;
  driver: string;
  riskNote: string;
  auctionMetrics?: AuctionMetric[];      // 新增：竞价指标
  sealRiskMetrics?: SealRiskMetric[];    // 新增：封单风险指标
}
```

**新增竞价指标卡片**：
```
┌─────────────────────────────────────────────────────────────┐
│  竞价阶段监控                                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  竞价换手率    2.3%    ████████████░░░░░░░░░░  阈值: 1%-5%  │
│  竞价成交额    ¥1,250万 ████████████░░░░░░░░░░  阈值: 100万-5000万 │
│  竞价量比      2.5x    ████████████░░░░░░░░░░  阈值: 0.5x-3.0x │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**新增封单风险卡片**：
```
┌─────────────────────────────────────────────────────────────┐
│  封单风险监控（绝对+相对双指标）                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  600519 贵州茅台                                             │
│  封单额: ¥500万 / 流通盘: 12.5亿股                          │
│  封单比例: 0.4%                                             │
│  要求比例: ≥10% (大盘股)                                     │
│  风险等级: 🔴 高风险                                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**交互行为**：
- **加载状态**：显示 5 个 Skeleton 进度条，shimmer 动画
- **数据更新**：进度条宽度平滑过渡 500ms
- **悬停效果**：鼠标悬停时显示因子详细说明 tooltip
- **错误状态**：显示"数据加载失败" + 重试按钮

**视觉规范**：
- 每个因子一行，左侧名称 + 权重标签，中间进度条，右侧分数
- 进度条颜色根据分数动态变化：<30 红色, 30-60 黄色, >60 绿色
- 权重标签使用 Badge 组件，小尺寸
- 综合评分区域使用 GlassCard 包裹，突出显示
- 趋势箭头：↑ 上升（绿色），↓ 下降（红色），→ 稳定（灰色）

**响应式行为**：
- **桌面端**：2 列网格布局，每列 2-3 个因子
- **平板/移动端**：单列布局，因子垂直堆叠

**无障碍**：
- 进度条使用 `role="progressbar"` + `aria-valuenow` + `aria-valuemin` + `aria-valuemax`
- 趋势箭头使用 `aria-label` 描述趋势方向

### 3.3 StrategyRecommendation (策略推荐卡片)

**职责**：根据当前天气状态，推荐最佳打板策略

**布局**：
```
┌─────────────────────────────────────────────────────────────┐
│  今日策略建议                                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  当前天气: 晴天 (主升浪)                                      │
│  推荐模式: 连板接力                                          │
│                                                             │
│  ✅ 连板接力 (匹配度: 85%)                                   │
│     - 追逐市场最高板、妖股                                    │
│     - 2连板以上 + 主线板块                                    │
│     - 条件单: 涨停价 - 0.02元 + 五档卖盘萎缩                 │
│                                                             │
│  ⚠️  首板挖掘 (匹配度: 45%)                                   │
│     - 低位首板套利，不适合当前环境                            │
│                                                             │
│  ❌ 弱转强反包 (匹配度: 20%)                                   │
│     - 极端反弹期专用，当前不适用                              │
│                                                             │
│  [查看完整战法库] [切换至半自动模式]                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件接口**：
```tsx
interface StrategyMatch {
  style: "连板接力" | "首板挖掘" | "弱转强反包";
  matchScore: number;      // 0-100
  enabled: boolean;
  description: string;
  conditions: string[];
  orderConfig: string;
  executionParams?: {      // 新增：执行参数
    channelLatencyMs: number;
    slippageCompensation: number;
    settlementBuyPrice: number;
    nextDaySellBase: number;
    t1Locked: boolean;
  };
}

interface StrategyRecommendationProps {
  weatherState: string;
  strategies: StrategyMatch[];
  onViewAll: () => void;
  onEnableSemiAuto: () => void;
}
```

**新增执行参数展示**：
```
┌─────────────────────────────────────────────────────────────┐
│  连板接力 (匹配度: 85%)                                       │
│                                                             │
│  条件单配置:                                                 │
│  触发条件: 价格 ≥ 涨停价 - 0.02元 且 五档卖盘萎缩            │
│  执行动作: 弹窗提示 + 人工确认后涨停价扫货                    │
│                                                             │
│  A股执行参数:                                                │
│  通道延迟: 200ms                                             │
│  滑点补偿: ±0.1% (涨停板: ±0.5%)                            │
│  预估买入价: ¥10.05 (竞价成交价)                             │
│  次日卖出基准: ¥10.08 (次日竞价开盘价)                       │
│  ⚠️ T+1锁定：当日买入不可卖出                                 │
│                                                             │
│  [查看详细战法库] [切换至半自动模式]                           │
└─────────────────────────────────────────────────────────────┘
```

**交互行为**：
- **加载状态**：显示 3 个 Skeleton 卡片，shimmer 动画
- **数据更新**：匹配度数字滚动动画
- **展开/收起**：点击策略卡片展开详细条件单配置
- **操作按钮**：
  - "查看完整战法库" → 跳转到战法库页面
  - "切换至半自动模式" → 打开半自动配置面板

**视觉规范**：
- 推荐策略使用绿色边框 + 绿色图标
- 不推荐策略使用灰色 + 降低透明度
- 匹配度使用圆形进度条或百分比 Badge
- 条件单配置使用代码块样式展示
- 当前激活策略使用高亮边框 + 微光效果

**响应式行为**：
- **桌面端**：3 列网格布局
- **平板/移动端**：单列垂直堆叠

**无障碍**：
- 策略卡片使用 `role="article"` + `aria-label` 描述策略类型和匹配度
- 匹配度进度条使用 `role="progressbar"`
- 按钮支持键盘导航

### 3.4 FuseRulesPanel (熔断规则面板)

**职责**：展示当前启用的熔断规则和状态

**布局**：
```
┌─────────────────────────────────────────────────────────────┐
│  熔断规则监控                                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🔴 仓位熔断                                                 │
│     状态: 已启用                                             │
│     触发条件: 天气=暴风雨 → 自动锁死交易权限                  │
│     当前状态: 正常 (天气=晴天)                                │
│                                                             │
│  🟡 撤单熔断                                                 │
│     状态: 已启用                                             │
│     触发条件: 封单<3000万 或 撤单/封单>20%                   │
│     当前状态: 监控中 (无异常)                                 │
│                                                             │
│  🔴 次日强制离场                                             │
│     状态: 已启用                                             │
│     触发条件: 未高开 或 开盘5分钟未站稳均线                   │
│     当前状态: 待触发 (无持仓)                                 │
│                                                             │
│  [编辑规则] [查看历史触发记录]                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件接口**：
```tsx
interface FuseRule {
  id: string;
  name: string;
  status: "enabled" | "disabled";
  triggerCondition: string;
  currentState: string;
  lastTriggered?: string;
  isPardoned?: boolean;        // 新增：是否已赦免
  pardonExpiresAt?: string;    // 新增：赦免到期时间
  pardonEnabledBy?: string;    // 新增：赦免开启人
}

interface FuseRulesPanelProps {
  rules: FuseRule[];
  onEdit: () => void;
  onViewHistory: () => void;
  onTogglePardon?: (ruleId: string, strategyCode: string) => void;  // 新增：切换赦免
  isAdmin?: boolean;  // 新增：是否管理员
}
```

**新增赦免管理区域**：
```
┌─────────────────────────────────────────────────────────────┐
│  仓位熔断赦免管理                                             │
│  ⚠️ 管理员权限 required                                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  战法名称          状态    开启人    到期时间    操作         │
│  首板挖掘          🔓 赦免  管理员A   2026-07-24  [撤销]      │
│  连板接力          🔒 锁定  -         -          [赦免]      │
│  弱转强反包        🔒 锁定  -         -          [赦免]      │
│                                                             │
│  [赦免规则说明]                                              │
│  - 赦免模式下最大仓位限制: 10%                                │
│  - 需要双人审批                                              │
│  - 24小时后自动撤销                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**交互行为**：
- **加载状态**：显示 3 个 Skeleton 规则项
- **状态切换**：启用/禁用规则时，显示确认对话框
- **展开详情**：点击规则项展开查看详细配置
- **赦免操作**：
  - 仅管理员可见"赦免"按钮
  - 点击"赦免"显示战法选择器 + 有效期设置 + 原因填写
  - 需要审批人确认（双人审批流程）
  - 赦免成功后显示倒计时
- **操作按钮**：
  - "编辑规则" → 打开规则编辑器模态框
  - "查看历史触发记录" → 跳转到熔断规则 Tab
  - "赦免管理" → 展开/收起赦免管理区域（仅管理员）

**视觉规范**：
- 启用状态：绿色圆点 + 绿色文字
- 禁用状态：灰色圆点 + 灰色文字
- 赦免状态：橙色圆点 + 橙色文字 + 倒计时徽章
- 触发条件使用等宽字体展示
- 当前状态使用 Badge 组件
- 异常状态使用红色高亮 + 脉冲动画
- 管理员操作区域使用边框区分：`border-l-4 border-orange-500`

**响应式行为**：
- **桌面端**：3 列网格布局
- **平板/移动端**：单列垂直堆叠

**无障碍**：
- 规则状态使用 `aria-live="polite"` 实时播报
- 状态指示灯使用 `aria-label` 描述
- 按钮支持键盘导航

### 3.5 WeatherTimelineChart (天气历史趋势)

**职责**：展示过去 30 天的天气状态变化和 STI 走势

**布局**：
```
┌─────────────────────────────────────────────────────────────┐
│  天气历史趋势 (近30天)                                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                                                     │   │
│  │  [ECharts 折线图 + 天气状态背景色带]                  │   │
│  │                                                     │   │
│  │  X轴: 日期                                           │   │
│  │  Y轴: STI 温度 (0-100)                               │   │
│  │  背景色带: 暴风雨(红) / 阴天(灰) / 晴天(橙) / 极端反弹(紫) │   │
│  │                                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  统计: 晴天 12天 | 阴天 8天 | 暴风雨 6天 | 极端反弹 4天      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**组件接口**：
```tsx
interface WeatherTimelineItem {
  date: string;
  stiScore: number;
  weatherState: string;
  phase: string;
}

interface WeatherTimelineChartProps {
  data: WeatherTimelineItem[];
  days?: number;
}
```

**交互行为**：
- **加载状态**：显示 Skeleton 图表占位
- **悬停效果**：鼠标悬停显示 tooltip，包含日期、STI 分数、天气状态
- **缩放/平移**：支持鼠标滚轮缩放，拖拽平移（可选）
- **图例交互**：点击图例显示/隐藏对应天气状态色带

**视觉规范**：
- 复用现有 `STITimelineChart` 的 ECharts 配置
- 添加天气状态背景色带（使用 markArea）
- 折线颜色根据天气状态动态变化
- 底部显示统计摘要
- 色带透明度 0.15，避免干扰折线

**响应式行为**：
- **桌面端**：图表宽度 100%，高度 400px
- **平板/移动端**：图表宽度 100%，高度 300px，简化 tooltip

**无障碍**：
- 图表使用 `role="img"` + `aria-label` 描述趋势
- 提供数据表格替代（可选）
- 颜色对比度符合 WCAG AA 标准

---

## 四、二级页面设计

### 4.1 实时天气 (默认页)

**内容**：
- WeatherHero 大卡片
- MultiFactorBreakdown 多因子分解
- StrategyRecommendation 策略推荐
- FuseRulesPanel 熔断规则监控

**数据流**：
```
SentimentWeather (主页面)
  ├── api.sentimentWeatherLatest() → 获取当前天气状态
  │   └── 包含: weatherState, stiScore, confidence, dataUpdated
  │   └── 包含: dataFreshness { isStale, delayMs, lastTriggerCount }
  │   └── 包含: executionParams { channelLatencyMs, slippageCompensation, settlementBuyPrice, nextDaySellBase, t1Locked }
  ├── api.sentimentWeatherFactors() → 获取多因子数据
  │   └── 包含: factors[] + auctionMetrics[] + sealRiskMetrics[]
  ├── api.sentimentWeatherStrategy() → 获取策略推荐
  │   └── 包含: strategies[] with executionParams per strategy
  ├── api.sentimentWeatherFuse() → 获取熔断规则状态
  │   └── 包含: rules[] with pardonRecords, isAdmin
  ├── api.sentimentWeatherAuction() → 获取竞价阶段指标（分阶段）
  └── api.sentimentWeatherSealRisk() → 获取封单风险数据
  └── api.sentimentWeatherPardon() → 获取赦免记录
  └── api.sentimentWeatherPardonToggle() → 切换赦免状态（POST）
  └── api.sentimentWeatherPardonRevoke() → 撤销赦免（POST）
  └── api.sentimentWeatherPardonOutcome() → 提交交易结果（POST）
```

**加载策略**：
- 页面进入时并行请求 4 个 API
- 使用 `Promise.all` 等待所有请求完成
- 部分失败时显示可用数据 + 警告提示
- 5 分钟自动刷新，手动刷新 < 3 秒

### 4.2 历史趋势

**内容**：
- WeatherTimelineChart 天气历史趋势图
- 天气状态统计卡片（各状态天数占比）
- 关键事件标注（政策发布、重大利好/利空）

**数据流**：
```
SentimentWeatherHistory
  ├── api.sentimentWeatherTimeline(days = 30) → 获取历史数据
  └── api.sentimentWeatherEvents() → 获取关键事件
```

**加载策略**：
- 默认加载近 30 天数据
- 支持切换时间范围：7天 / 30天 / 90天
- 图表懒加载，进入视口时再渲染

### 4.3 策略建议

**内容**：
- 8 大战法详细说明卡片
- 当前天气下的策略匹配度矩阵
- 策略切换历史记录
- 半自动工作流配置面板

**数据流**：
```
SentimentWeatherStrategy
  ├── api.sentimentWeatherStrategies() → 获取策略列表
  ├── api.sentimentWeatherMatch() → 获取匹配度
  └── api.sentimentWeatherConfig() → 获取用户配置
```

**加载策略**：
- 策略列表缓存 1 小时
- 匹配度实时计算，显示加载状态
- 配置变更时自动保存

### 4.4 熔断规则

**内容**：
- FuseRulesPanel 规则监控
- 历史触发记录表格
- 规则编辑器（启用/禁用、调整阈值）

**数据流**：
```
SentimentWeatherFuse
  ├── api.sentimentWeatherFuse() → 获取当前规则状态
  ├── api.sentimentWeatherFuseHistory() → 获取触发历史
  └── api.sentimentWeatherFuseUpdate() → 更新规则配置
```

**加载策略**：
- 规则状态实时刷新（WebSocket 或轮询）
- 历史记录分页加载，每页 20 条
- 规则编辑后立即生效，无需刷新

---

## 五、全局状态与错误处理

### 5.1 加载状态规范

**Skeleton 组件**：
- 使用现有 `Skeleton` 组件，shimmer 动画
- 卡片骨架：`<Skeleton className="h-32 w-full" />`
- 图表骨架：`<Skeleton className="h-64 w-full" />`
- 列表骨架：`<Skeleton className="h-12 w-full" />`

**加载时机**：
- 页面进入：立即显示骨架屏
- Tab 切换：显示对应 Tab 的骨架屏
- 数据刷新：保留旧数据，显示刷新指示器

### 5.2 错误状态规范

**网络错误**：
```tsx
<div className="flex flex-col items-center justify-center p-8">
  <AlertCircle className="h-12 w-12 text-red-500" />
  <p className="mt-4 text-lg font-medium">数据加载失败</p>
  <p className="mt-2 text-sm text-white/60">请检查网络连接后重试</p>
  <Button onClick={retry} className="mt-4">
    重试
  </Button>
</div>
```

**数据缺失**：
```tsx
<div className="flex flex-col items-center justify-center p-8">
  <Clock className="h-12 w-12 text-yellow-500" />
  <p className="mt-4 text-lg font-medium">数据暂未更新</p>
  <p className="mt-2 text-sm text-white/60">
    最后更新时间: {lastUpdated}
  </p>
  <Button onClick={refresh} className="mt-4">
    立即刷新
  </Button>
</div>
```

**降级策略**：
- 部分数据失败时，显示可用数据 + 警告提示
- 使用黄色警告条：`<div className="bg-yellow-500/10 border border-yellow-500/50 ...>`
- 记录错误日志，包含失败 API 和错误信息

### 5.3 空状态规范

**无数据状态**：
```tsx
<div className="flex flex-col items-center justify-center p-8">
  <Inbox className="h-12 w-12 text-white/30" />
  <p className="mt-4 text-lg font-medium">暂无数据</p>
  <p className="mt-2 text-sm text-white/60">
    当前没有可显示的数据
  </p>
</div>
```

**适用场景**：
- 历史趋势无数据
- 策略列表为空
- 熔断规则未配置

---

## 五、组件层级结构

```
SentimentWeather (主页面容器)
  ├── PageHeader
  │   ├── title: "情绪气象站"
  │   ├── subtitle: "市场情绪天气 · 策略自动切换中枢"
  │   └── actions: [刷新按钮] [设置按钮] [管理员赦免入口]
  │
  ├── WeatherHero (天气状态大卡片)
  │   ├── 天气图标 (lucide-react: CloudSun, CloudRain, Sun, Zap)
  │   ├── 天气状态文字
  │   ├── STI 温度计 (ECharts gauge)
  │   ├── 情绪指数 + 置信度
  │   ├── 数据新鲜度指示器 (延迟/死循环计数)
  │   ├── 执行参数摘要 (通道延迟/滑点/结算价)
  │   └── 操作按钮
  │
  ├── SecondaryTabs (二级导航)
  │   ├── 实时天气
  │   ├── 历史趋势
  │   ├── 策略建议
  │   └── 熔断规则
  │
  └── TabContent (动态内容区)
      ├── 实时天气 Tab
      │   ├── MultiFactorBreakdown
      │   │   └── AuctionMetricsCard (竞价指标)
      │   │   └── SealRiskCard (封单风险)
      │   ├── StrategyRecommendation
      │   │   └── 执行参数展示
      │   └── FuseRulesPanel
      │       └── PardonManagement (赦免管理，仅管理员)
      │
      ├── 历史趋势 Tab
      │   ├── WeatherTimelineChart
      │   └── WeatherStatsCards
      │
      ├── 策略建议 Tab
      │   ├── StrategyMatrix
      │   ├── StrategyDetailCards
      │   └── SemiAutoConfig
      │
      └── 熔断规则 Tab
          ├── FuseRulesPanel (详细版)
          ├── FuseHistoryTable
          ├── FuseRuleEditor
          └── PardonManagement (赦免管理)
```

---

## 六、视觉设计规范

### 6.1 颜色系统

**天气状态颜色映射**：

| 天气状态 | 主色 | 渐变背景 | 图标 | 情绪 |
|---------|------|---------|------|------|
| ⛈️ 暴风雨 | `#ef4444` (red-500) | `from-gray-900 to-blue-900` | CloudRain | 退潮期 |
| ⛅ 阴天 | `#6b7280` (gray-500) | `from-gray-100 to-blue-100` | Cloud | 震荡轮动 |
| ☀️ 晴天 | `#f97316` (orange-500) | `from-orange-100 to-yellow-100` | Sun | 主升浪 |
| 🌪️ 极端反弹 | `#a855f7` (purple-500) | `from-purple-100 to-pink-100` | Zap | 冰点反转 |

**STI 温度计颜色**：
- 0-30°C (冰点): `#3b82f6` (blue-500)
- 30-50°C (启动): `#22c55e` (green-500)
- 50-70°C (分歧): `#eab308` (yellow-500)
- 70-85°C (高潮): `#f97316` (orange-500)
- 85-100°C (过热): `#ef4444` (red-500)

### 6.2 字体规范

- **标题**: `text-2xl font-bold tracking-tight`
- **副标题**: `text-lg text-white/70`
- **天气状态**: `text-4xl font-bold`
- **STI 分数**: `text-5xl font-bold tabular-nums`
- **因子名称**: `text-sm font-medium`
- **因子分数**: `text-2xl font-bold tabular-nums`
- **说明文字**: `text-sm text-white/60`

### 6.3 间距规范

- **卡片间距**: `mb-6` (24px)
- **卡片内边距**: `p-6` (24px)
- **元素间距**: `gap-4` (16px)
- **紧凑间距**: `gap-2` (8px)

### 6.4 动画规范

- **页面进入**: `PageTransition` 组件，fade + slide up
- **天气状态切换**: 背景渐变过渡 `transition-all duration-500`
- **数据更新**: 数字滚动动画（可选）
- **按钮交互**: hover 时 lift 效果 `hover:-translate-y-0.5`
- **加载状态**: Skeleton 组件，shimmer 动画

---

## 七、响应式设计

### 7.1 断点策略

```tsx
// 移动端: < 768px
// 平板: 768px - 1024px
// 桌面: > 1024px
```

### 7.2 布局适配

**桌面端 (>1024px)**：
- 侧边栏展开，显示完整导航
- WeatherHero 横向布局：左侧天气状态，右侧 STI 温度计
- MultiFactorBreakdown 使用 2 列网格

**平板端 (768px-1024px)**：
- 侧边栏折叠为图标模式
- WeatherHero 纵向堆叠
- MultiFactorBreakdown 单列布局

**移动端 (<768px)**：
- 侧边栏隐藏，通过汉堡菜单打开
- 所有卡片全宽显示
- 字体大小适当缩小
- 二级导航改为底部 Tab Bar（可选）

---

## 八、无障碍设计

### 8.1 颜色对比度

- 所有文字与背景对比度 ≥ 4.5:1 (WCAG AA)
- 重要文字与背景对比度 ≥ 7:1 (WCAG AAA)
- 天气状态颜色不单独作为信息传递手段，配合图标和文字

### 8.2 键盘导航

- 所有交互元素支持 Tab 键导航
- 二级导航支持左右箭头键切换
- 按钮支持 Enter/Space 激活

### 8.3 屏幕阅读器

- 天气状态使用 `aria-live="polite"` 实时播报
- STI 温度计使用 `role="img"` + `aria-label` 描述
- 图表使用 `role="img"` + `aria-label` 或提供数据表格替代

---

## 九、数据流与状态管理

### 9.1 数据获取策略

```tsx
// 实时天气页面
useEffect(() => {
  let mounted = true;
  setLoading(true);
  
  Promise.all([
    api.sentimentWeatherLatest(),
    api.sentimentWeatherFactors(),
    api.sentimentWeatherStrategy(),
    api.sentimentWeatherFuse(),
  ])
    .then(([weather, factors, strategy, fuse]) => {
      if (mounted) {
        setWeather(weather);
        setFactors(factors);
        setStrategy(strategy);
        setFuse(fuse);
      }
    })
    .catch(error => setError(error.message))
    .finally(() => mounted && setLoading(false));
  
  // 每 5 分钟自动刷新
  const interval = setInterval(refresh, 5 * 60 * 1000);
  return () => { mounted = false; clearInterval(interval); };
}, []);
```

**数据获取原则**：
- **并行请求**：使用 `Promise.all` 并行获取独立数据
- **缓存策略**：5 分钟缓存，避免频繁请求
- **错误隔离**：单个 API 失败不影响其他数据展示
- **自动刷新**：5 分钟自动刷新，页面可见时生效
- **手动刷新**：提供刷新按钮，点击后立即更新

### 9.2 状态管理

- **本地状态**: `useState` 管理页面级状态
- **URL 状态**: 二级 Tab 使用 `useSearchParams` 或路由参数
- **缓存策略**: React Query 或 SWR（可选，Phase 2）
- **全局状态**: 无需全局状态管理，数据独立

**状态结构**：
```tsx
interface SentimentWeatherState {
  weather: WeatherState | null;
  factors: FactorScore[] | null;
  auction_metrics: AuctionMetric[] | null;      // 新增
  seal_risk_metrics: SealRiskMetric[] | null;   // 新增
  strategy: StrategyMatch[] | null;
  fuse: FuseRule[] | null;
  pardon_records: FusePardonRecord[] | null;    // 新增
  is_admin: boolean;                            // 新增
  loading: boolean;
  error: string | null;
  last_updated: string | null;
}
```

### 9.3 错误处理

- **网络错误**: 显示错误提示 + 重试按钮
- **数据缺失**: 显示 "数据暂未更新" + 最后更新时间
- **降级策略**: 部分数据失败时，显示可用数据 + 警告提示

**错误处理流程**：
1. 捕获网络错误，记录到日志
2. 显示用户友好的错误提示
3. 提供重试按钮
4. 部分失败时，显示可用数据 + 警告条
5. 自动重试机制（可选，Phase 2）

### 9.4 性能优化

- **数据缓存**: 5 分钟缓存，避免频繁请求
- **组件懒加载**: 二级 Tab 内容按需加载
- **图表优化**: ECharts 实例复用，避免重复创建
- **图片优化**: 天气图标使用 lucide-react，无需额外资源
- **代码分割**: 二级页面路由懒加载

---

## 十、实现优先级

### Phase 1 (Week 1-2): 核心页面 + 风险控制基础

1. **WeatherHero 组件** - 天气状态展示 + STI 温度计 + 数据新鲜度 + 执行参数
2. **MultiFactorBreakdown 组件** - 多因子分解 + 竞价指标 + 封单风险
3. **基础页面布局** - 路由 + 侧边栏 + 二级导航
4. **后端 API** - `/api/sentiment/weather/latest`, `/api/sentiment/weather/factors`, `/api/sentiment/weather/auction`, `/api/sentiment/weather/seal-risk`
5. **数据新鲜度校验** - 前端显示 + 死循环检测
6. **A股执行参数** - 滑点补偿 + 价格校验 + 成交量检查

### Phase 2 (Week 3-4): 策略与熔断增强

7. **StrategyRecommendation 组件** - 策略推荐 + 执行参数展示
8. **FuseRulesPanel 组件** - 熔断规则监控 + 赦免管理基础
9. **实时天气 Tab 完整功能**
10. **结算买入价逻辑** - 前端展示 + 成本计算
11. **赦免战法开关** - 管理员界面 + 双人审批流程

### Phase 3 (Week 5-6): 历史与策略完善

12. **WeatherTimelineChart 组件** - 历史趋势图
13. **历史趋势 Tab**
14. **策略建议 Tab**
15. **熔断规则 Tab 完整功能**
16. **赦免结果跟踪** -  outcome tracking + 审计日志

---

## 十一、技术实现要点

### 11.1 后端 API 规范

```python
# backend/routers/sentiment_weather.py

@router.get("/api/sentiment/weather/latest")
def get_weather_latest() -> Dict[str, Any]:
    """获取当前天气状态"""
    return {
        "weather_state": "晴天",
        "sti_score": 72,
        "sti_phase": "启动",
        "confidence": "高",
        "data_updated": "2026-07-23 15:05:00",
        "factors": {
            "sti": {"score": 72, "weight": 0.4},
            "risk": {"score": 65, "weight": 0.2},
            "sector_continuity": {"score": 78, "weight": 0.25},
            "capital_momentum": {"score": 70, "weight": 0.1},
            "public_sentiment": {"score": 68, "weight": 0.05},
        }
    }
```

**API 响应规范**：
- 统一使用 JSON 格式
- 包含 `source_ok` 字段标识数据源状态
- 包含 `last_updated` 时间戳
- 错误时返回 `error` 字段 + HTTP 状态码

### 11.2 前端组件规范

```tsx
// 所有组件使用 GlassCard 包裹
// 加载状态使用 Skeleton 组件
// 错误状态使用 ApiError 处理
// 数据更新使用 key 属性强制重渲染
```

**组件规范**：
- 所有卡片组件使用 `GlassCard` 包裹
- 加载状态统一使用 `Skeleton` 组件
- 错误状态统一使用 `ApiError` 组件
- 数据更新使用 `key` 属性强制重渲染
- 所有交互元素支持键盘导航

### 11.3 性能优化

- **数据缓存**: 5 分钟缓存，避免频繁请求
- **组件懒加载**: 二级 Tab 内容按需加载
- **图表优化**: ECharts 实例复用，避免重复创建
- **图片优化**: 天气图标使用 lucide-react，无需额外资源
- **代码分割**: 二级页面路由懒加载

**性能指标**：
- 首屏加载 < 2 秒
- API 响应 P95 < 500ms
- 交互响应 < 100ms
- 图表渲染 < 500ms

### 11.4 类型安全

```tsx
// 所有 API 响应类型定义
interface WeatherState {
  weather_state: string;
  sti_score: number;
  sti_phase: string;
  confidence: string;
  data_updated: string;
  data_freshness: {
    is_stale: boolean;
    delay_ms: number;
    last_trigger_count: number;
  };
  execution_params?: {
    channel_latency_ms: number;
    slippage_compensation: number;
    settlement_buy_price: number;
    next_day_sell_base: number;
    t1_locked: boolean;
  };
}

interface FactorScore {
  name: string;
  score: number;
  weight: number;
  trend: "up" | "down" | "stable";
  explanation: string;
}

interface AuctionMetric {
  name: string;
  value: number;
  unit: string;
  phase: "pre_competitive" | "competitive";
  threshold_high: number;
  threshold_low: number;
  is_warning: boolean;
}

interface SealRiskMetric {
  stock_code: string;
  seal_amount: number;        // 封单额（元）
  float_shares: number;       // 流通盘（股）
  seal_ratio: number;         // 封单比例
  min_ratio_required: number;  // 最低要求比例
  risk_level: "low" | "medium" | "high";
  cap_category: string;
  enforcement_action: string;
  reason: string;
}

interface StrategyMatch {
  style: "连板接力" | "首板挖掘" | "弱转强反包";
  match_score: number;
  enabled: boolean;
  description: string;
  conditions: string[];
  order_config: string;
  execution_params?: {
    channel_latency_ms: number;
    slippage_compensation: number;
    settlement_buy_price: number;
    next_day_sell_base: number;
    t1_locked: boolean;
  };
}

interface FuseRule {
  id: string;
  name: string;
  status: "enabled" | "disabled";
  trigger_condition: string;
  current_state: string;
  last_triggered?: string;
  is_pardoned?: boolean;
  pardon_expires_at?: string;
  pardon_enabled_by?: string;
}

interface FusePardonRecord {
  id: string;
  strategy_code: string;
  strategy_name: string;
  enabled_by: string;
  enabled_ip: string;
  approved_by: string;
  max_position_pct: number;
  created_at: string;
  expires_at: string;
  reason: string;
  is_active: boolean;
  revoked_at?: string;
  revoked_by?: string;
  outcome?: {
    stock_code: string;
    entry_price: number;
    exit_price: number;
    return_pct: number;
    was_successful: boolean;
    lessons_learned: string;
  };
}
```

**类型规范**：
- 所有 API 响应定义 TypeScript 接口
- 使用 `zod` 或 `io-ts` 进行运行时类型验证（可选）
- 组件 Props 必须定义完整类型

---

## 十二、附录

### 12.1 组件清单

| 组件 | 路径 | 职责 |
|------|------|------|
| SentimentWeather | `pages/SentimentWeather.tsx` | 主页面容器 |
| WeatherHero | `components/sentiment-weather/WeatherHero.tsx` | 天气状态大卡片 + 数据新鲜度 + 执行参数 |
| MultiFactorBreakdown | `components/sentiment-weather/MultiFactorBreakdown.tsx` | 多因子分解 + 竞价指标 + 封单风险 |
| StrategyRecommendation | `components/sentiment-weather/StrategyRecommendation.tsx` | 策略推荐 + 执行参数展示 |
| FuseRulesPanel | `components/sentiment-weather/FuseRulesPanel.tsx` | 熔断规则监控 + 赦免管理 |
| WeatherTimelineChart | `components/sentiment-weather/WeatherTimelineChart.tsx` | 历史趋势图 |
| WeatherStatsCards | `components/sentiment-weather/WeatherStatsCards.tsx` | 统计卡片 |
| AuctionMetricsCard | `components/sentiment-weather/AuctionMetricsCard.tsx` | 竞价指标卡片（新增） |
| SealRiskCard | `components/sentiment-weather/SealRiskCard.tsx` | 封单风险卡片（新增） |
| PardonManagement | `components/sentiment-weather/PardonManagement.tsx` | 赦免管理面板（新增） |

### 12.2 API 端点清单

| 端点 | 方法 | 职责 |
|------|------|------|
| `/api/sentiment/weather/latest` | GET | 获取当前天气状态 + 数据新鲜度 + 执行参数 |
| `/api/sentiment/weather/factors` | GET | 获取多因子数据 + 竞价指标 + 封单风险 |
| `/api/sentiment/weather/strategy` | GET | 获取策略推荐 + 执行参数 |
| `/api/sentiment/weather/fuse` | GET | 获取熔断规则状态 + 赦免记录 |
| `/api/sentiment/weather/timeline` | GET | 获取历史趋势数据 |
| `/api/sentiment/weather/events` | GET | 获取关键事件 |
| `/api/sentiment/weather/auction` | GET | 获取竞价阶段指标（新增） |
| `/api/sentiment/weather/seal-risk` | GET | 获取封单风险数据（新增） |
| `/api/sentiment/weather/pardon` | GET | 获取赦免记录（新增） |
| `/api/sentiment/weather/pardon/toggle` | POST | 切换战法赦免状态（新增，管理员） |

### 12.3 设计参考

- 现有 STI 组件: `components/sti/StiCard.tsx`, `STITimelineChart.tsx`
- 现有页面: `pages/DailyReview.tsx`
- 设计系统: `index.css` (Glass-morphism 主题)

---

## 十三、下一步行动

1. **确认设计**：与产品/设计团队确认本设计文档
2. **后端开发**：
   - 实现 10 个 API 端点（含新增的 auction/seal-risk/pardon）
   - 实现数据新鲜度校验、A股通道参数、结算买入价逻辑、封单风险双指标
   - 实现赦免战法开关逻辑（双人审批 + 自动撤销）
3. **前端开发**：
   - Phase 1: WeatherHero + MultiFactorBreakdown + 基础布局
   - Phase 2: StrategyRecommendation + FuseRulesPanel + 赦免管理
   - Phase 3: AuctionMetricsCard + SealRiskCard + 历史趋势 + 策略建议
4. **集成测试**：与现有 STI 系统联调 + 新增风险控制场景测试
5. **用户测试**：邀请种子用户验证可用性
6. **迭代优化**：根据反馈调整权重模型和 UI

---

## 十四、V2.0.3 关键修复清单

| 修复项 | 优先级 | 状态 | 负责模块 |
|--------|--------|------|---------|
| 日内数据延迟与死循环防护 | P0 | 待实施 | 后端 + 前端 |
| A股通道速度与滑点补偿 | P0 | 待实施 | 后端 + 前端 |
| 结算买入价逻辑悖论修正 | P0 | 待实施 | 后端 + 前端 |
| 绝对封单额/流通盘风险控制 | P0 | 待实施 | 后端 + 前端 |
| 竞价换手率/竞价成交额监控 | P1 | 待实施 | 后端 + 前端 |
| 仓位熔断管理员赦免战法开关 | P1 | 待实施 | 后端 + 前端 |

---

## 十四、V2.0.3 关键修复清单

| 修复项 | 优先级 | 状态 | 负责模块 |
|--------|--------|------|---------|
| 日内数据延迟与死循环防护 | P0 | 设计完成 | WeatherHero + 后端 |
| A股通道速度与滑点补偿 | P0 | 设计完成 | StrategyRecommendation + 后端 |
| 结算买入价逻辑悖论修正 | P0 | 设计完成 | StrategyRecommendation + 后端 |
| 绝对封单额/流通盘风险控制 | P0 | 设计完成 | MultiFactorBreakdown + 后端 |
| 竞价换手率/竞价成交额监控 | P1 | 设计完成 | AuctionMetricsCard + 后端 |
| 仓位熔断管理员赦免战法开关 | P1 | 设计完成 | FuseRulesPanel + PardonManagement + 后端 |

---

## 十五、设计验证检查清单

### 15.1 数据新鲜度与死循环防护

- [ ] WeatherHero 显示数据延迟时间（毫秒级）
- [ ] 过期数据（>10秒）显示黄色警告条
- [ ] 死循环检测显示触发计数（X/3次）
- [ ] 触发上限后自动锁定并显示倒计时
- [ ] 条件单按钮在数据过期时禁用

### 15.2 A股执行参数展示

- [ ] 显示通道延迟（区分竞价/连续交易阶段）
- [ ] 显示滑点补偿（普通/涨停板/跌停板）
- [ ] 显示预估买入价（含滑点）
- [ ] 显示次日卖出基准价
- [ ] T+1锁定提示清晰可见
- [ ] 成交量校验结果展示

### 15.3 封单风险监控

- [ ] 显示封单额（万元）
- [ ] 显示流通盘（亿股）
- [ ] 显示封单比例（%）
- [ ] 显示动态阈值（根据流通盘分类）
- [ ] 风险等级颜色编码（绿/黄/红）
- [ ] 执行动作明确（允许/降级/禁止）

### 15.4 竞价指标监控

- [ ] 区分9:15-9:20和9:20-9:25两个阶段
- [ ] 显示竞价换手率、成交额、量比
- [ ] 阈值高亮（黄色/红色）
- [ ] 阶段切换提示

### 15.5 赦免管理

- [ ] 仅管理员可见赦免按钮
- [ ] 双人审批流程界面
- [ ] 2FA验证集成
- [ ] 赦免倒计时显示
- [ ] 手动撤销功能
- [ ] 结果跟踪界面（成功/失败/进行中）
- [ ] 审计日志完整（开启人/审批人/IP/时间）

---

*本文档由 Orchestrator + @designer 生成，基于 Vibe-Research 现有设计系统和用户需求。*
