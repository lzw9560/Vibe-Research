# S092 三视图 UI 原型 · 设计说明

> 配套文件：`ui-prototype.html`（单 HTML，内联 CSS，可直接浏览器打开）
> 主题复刻：`frontend/src/index.css` 的"科技玻璃暖橙"主题（深蓝黑底 + 暖橙红 #F35D2B + `.glass` 玻璃拟态）
> 日期：2026-08-21

---

## 1. 视觉系统

### 1.1 主题与配色

完整复刻现有设计系统（`frontend/src/index.css`），零新色板：

| 语义 | CSS 变量 | 色值 | 用途 |
|---|---|---|---|
| 背景 | `--background` | `hsl(222 47% 6%)` 深蓝黑 | 页面纵深底 |
| 主色 | `--primary` | `hsl(15 89% 56%)` ≈ #F35D2B 暖橙红 | 标题光晕、Tab 激活、F 锚值、按钮主色 |
| 成功 | `--success` | `hsl(145 62% 47%)` | 任务 done、数据就绪 |
| 危险 | `--danger` | `hsl(0 74% 60%)` | 任务 error |
| 警告 | `--warning` | `hsl(38 92% 55%)` 琥珀 | 过渡窗"采集中"、待产出占位 |
| 运行 | `--running` | `hsl(199 89% 58%)` 蓝 | 任务 running 脉冲（与品牌橙区分） |
| 静默 | `--muted-foreground` | `hsl(215 18% 62%)` | 次要文字 |

**关键决策**：任务 `running` 状态刻意不用品牌橙，而用蓝色——因为品牌橙在 UI 中已大量用于 Tab 激活、F 锚值、标题光晕，若 running 也用橙会跟"激活/强调"语义混淆。蓝色脉冲在暖橙基调中跳出但不冲突，形成清晰的"系统正在工作"信号。

### 1.2 字体

避开通用 Inter/Arial，三字族组合建立层次：

| 字族 | 字体 | 用途 | 理由 |
|---|---|---|---|
| 标题 | Noto Serif SC（宋体衬线） | PageHeader h1、区块标题、视图主标题 | 金融报告质感，衬线在深底上有出版物的权威感 |
| 正文 | Noto Sans SC | 段落、标签、按钮 | 可读性 |
| 数字 | JetBrains Mono | 日期、时间、价格、得分、状态计数 | 等宽对齐，数据密集场景护眼，`font-feature-settings: "tnum"` 等宽数字 |

### 1.3 玻璃拟态

完整复刻 `.glass` + `.glass-glow`：
- 半透明渐变填充（`linear-gradient(162deg, fill-top, fill-bot)`）
- 发丝边框（`rgba(255,232,214,0.10)`）
- 柔投影 + 顶部内高光（`box-shadow + inset`）
- `backdrop-filter: blur(14px)`
- `.glass-glow` 右上角暖橙光晕装饰热点

背景双光晕（顶橙 + 右下冷蓝）固定不滚动，营造纵深。

---

## 2. 布局结构

原型从上到下五层：

```
┌─────────────────────────────────────────────┐
│ PageHeader（标题 + date picker + 刷新）      │  ← 复用 PageHeader 风格
├─────────────────────────────────────────────┤
│ AnchorBar 锚条（F + 三视图数据日 + 时段标签）  │  ← 新建
├─────────────────────────────────────────────┤
│ TaskStatusCard 任务状态卡片（公共区常驻）     │  ← 新建
├─────────────────────────────────────────────┤
│ TabBar（复盘 / 当日 / 前瞻）                  │  ← 复用 TabBar 胶囊样式
├─────────────────────────────────────────────┤
│ Tab Panel（当前 Tab 的视图组件内容）          │  ← 复用三个视图组件
└─────────────────────────────────────────────┘
```

### 2.1 AnchorBar（锚条）— 新建

三栏 grid 布局（`auto 1fr auto`）：

- **左**：F 锚值。小号大写 label "锚定交易日 F" + 大号等宽橙色日期 + 周几。
- **中**：三视图数据日。三个 node（复盘/当日/前瞻）用发丝线连接，每个 node 显示角色名 + 数据日。过渡窗前瞻 node 的日期变琥珀色"待 17:15 产出"。
- **右**：时段标签。过渡窗=琥珀色"数据采集中"（带脉冲圆点），就绪=绿色"数据就绪"。

响应式：窄屏三栏堆叠为单列。

### 2.2 TaskStatusCard（任务状态卡片）— 新建

公共区常驻，与 Tab 无关。结构：

- **Header**：标题"盘后采集任务" + 进度徽章（`2/8`）+ 摘要文字 + 折叠箭头
- **Body**：纵向时间线，8 个 cron 任务按时间序排列

**过渡窗 vs 就绪态差异**：
- 过渡窗（15:00-17:15）：Body 展开，显示完整时间线，每个任务节点带状态色 + running 脉冲
- 就绪态（17:15 后）：Body 折叠为摘要条（"全部 8 项已完成 · 17:15 F 已推进"），用户点击可展开

**时间线节点状态**：

| 状态 | 节点样式 | 徽章 | "载入"按钮 |
|---|---|---|---|
| pending | 灰色空心圆 | 灰 pill | 无 |
| running | 蓝色脉冲圆（`pulse-node` 动画） | 蓝 pill | 无 |
| done | 绿色实心圆 | 绿 pill | **显示**（触发对应视图 refetch） |
| error | 红色半实心圆 | 红 pill | 无（需手动重跑） |

点击任务项展开详情（cron 表达式、上次执行时间、耗时、日志）。

### 2.3 TabBar — 复用

复用现有 `TabBar.tsx` 胶囊样式（`bg-muted/30` 容器 + 激活态 `bg-primary/15 text-primary shadow-sm`），但做了一处增强：激活 Tab 前加一个小圆点指示器，强化"当前角色"的视觉锚定。三 Tab：复盘 / 当日 / 前瞻。

### 2.4 Tab Panel 内容

**复盘 Tab**（PostMarketReview）：
- ① 涨停池/情绪/梯队（15:00 实时可得）→ MetricCard 网格
- ② 基因得分/STI/漏斗候选 → 过渡窗显示 4 个"待 {cron时间} 产出"虚线占位卡；就绪态显示完整 MetricCard
- ③ 盘后三问（S054）→ 文本卡，三个加粗问题 + 回答

**当日 Tab**（PreMarketBriefing）：
- 顶部 WeatherDecisionBar（S063）→ 天气图标 + 情绪名 + STI/仓位上限
- 盘后简报快照标注（蓝 info banner："数据为今早盘前采集口径，17:15 后可刷新"）
- 情绪→漏斗→候选池 管线流程徽章
- 候选/观察/持仓/已结 MetricCard 网格
- ④ 行为对照卡（S050 ShadowComparison）→ 票根 vs 影子收益双栏对比 + lift 倍数
- ⑤ 暴风雨预测（S088）→ 当前无信号 + 安全徽章
- ⑥ 盯盘链接卡 → 跳转 `/workflow/intraday` 独立路由

**前瞻 Tab**（PremarketSelectionSection）：
- 过渡窗：大号"盘后选股采集中"占位（📡 图标 + "kline 日更 16:30 完成后产出"）
- 就绪态：候选数/均得分/风控触发/生成时间 MetricCard 网格 + T+1 标的池列表（排名 + 名称 + 代码 + 得分 + 买入价/止损价）

---

## 3. 状态映射

### 3.1 任务今日完成状态 → 颜色/图标/交互

| `today_status` | 节点圆 | 徽章色 | "载入"按钮 | 交互 |
|---|---|---|---|---|
| `pending` | 灰空心 | 灰 `pill pending` | 无 | 可点击展开详情 |
| `running` | 蓝脉冲（`pulse-node` 动画） | 蓝 `pill running` | 无 | 可点击展开详情 |
| `done` | 绿实心 | 绿 `pill done` | **显示** → 触发对应视图 refetch | 可点击展开详情 |
| `error` | 红半实心 | 红 `pill error` | 无（需手动重跑 `POST /api/scheduled-tasks/{id}/run`） | 可点击展开详情 |

### 3.2 时段 → Tab 自动高亮 → 锚条状态

| 时段 | `stage` | 自动高亮 Tab | 锚条时段标签 | 任务卡片 |
|---|---|---|---|---|
| 盘前 00:00-09:29 | `pre_market` | 前瞻 | （不显示采集标签） | 折叠摘要 |
| 盘中 09:30-14:59 | `intraday` | 当日 | （不显示采集标签） | 折叠摘要 |
| 盘后过渡 15:00-17:15 | `post_transition` | **复盘** | 琥珀"数据采集中"（脉冲） | **展开**，60s 轮询 |
| 盘后 17:15+ | `post_market` | **前瞻** | 绿"数据就绪" | 折叠摘要 |
| 非交易日 | `non_trading` | 复盘（最近交易日） | "非交易日，无采集任务" | 折叠摘要 |

### 3.3 三视图数据日 → 锚条显示

| 时段 | F | 复盘数据日 | 当日数据日 | 前瞻数据日 |
|---|---|---|---|---|
| 盘前 | T-1 | T-1 | T（生成中） | T |
| 盘中 | T-1 | T-1 | T（实时） | T |
| **过渡窗** | T-1（不变） | **T**（独立推进） | T-1（简报快照） | "待 17:15 产出"（琥珀色） |
| **盘后就绪** | T（推进） | T（完整） | T（简报快照+可刷新） | T+1（完整） |

---

## 4. 交互流程

### 4.1 定时器推进时的 UI 变化

**15:00 复盘独立推进**（`next_review_advance_at` 定时器触发）：
1. 锚条：复盘数据日从 T-1 → T（F 不变，仍 T-1）
2. 复盘 Tab：① 涨停池/情绪区立即显示 T 日实时数据；② 未产出区显示"待 {cron时间} 产出"占位
3. 任务卡片：从折叠摘要 → 展开，显示完整时间线，所有任务初始 pending
4. 启动 60s 轮询 `GET /api/scheduled-tasks`

**17:15 F 推进**（`next_f_advance_at` 定时器触发）：
1. 锚条：F 从 T-1 → T；三视图数据日全部刷新（当日=T、前瞻=T+1）
2. 时段标签：琥珀"采集中" → 绿"数据就绪"
3. 三视图全量 refetch：
   - 复盘：占位区消失，显示完整 T 日数据
   - 当日：简报快照标注消失（或保留"可刷新"提示）
   - 前瞻：采集中占位 → 完整 T+1 标的池
4. 任务卡片：展开 → 折叠为摘要条（"全部 8 项已完成"）
5. 自动切换高亮 Tab：复盘 → 前瞻（核心动作=选 T+1）
6. 停止 60s 轮询

### 4.2 任务变 done 时的 UI 变化（过渡窗轮询驱动）

以 15:30 基因得分任务为例：
1. 15:29 轮询：`today_status=pending` → 节点灰色空心，无"载入"按钮
2. 15:30:08 轮询：`today_status=running` → 节点变蓝脉冲，徽章变蓝
3. 15:30:12 轮询：`today_status=done` → 节点变绿实心，徽章变绿，**出现"载入"按钮**
4. 用户点击"载入" → 触发对应视图 refetch（复盘 Tab 的基因得分区从占位 → 数据）
5. 摘要文字 + 进度徽章更新（`1/8` → `2/8`）

**前瞻特殊路径**：kline 日更（16:30）任务变 done 后，前瞻 Tab 的"载入"按钮可提前触发前瞻 refetch（不必等 17:15）。这是 R3b 的"16:30 后可手动载入"路径。

### 4.3 手动日期交互

- 用户选 date → 锚条 F 覆盖为所选日期，三视图以该 F 推算
- 定时器暂停（不覆盖手动选择）
- 清除 date → 恢复自动态，定时器重新激活

---

## 5. 组件复用与新建清单

### 5.1 复用现有组件

| 组件 | 复用点 | 改动 |
|---|---|---|
| `GlassCard` | 所有卡片容器 | 无（直接用 `.glass` class） |
| `PageHeader` | 顶部标题区 | 无（传 title/subtitle/actions） |
| `TabBar` | 三 Tab 切换 | 无（传 tabs/activeKey/onChange），原型额外加了激活圆点指示器 |
| `MetricCard` | 各视图的指标网格 | 无 |
| `Badge` | 状态徽章、管线流程 | 无 |
| `Button` | 刷新、载入、清除日期 | 无 |
| `Skeleton` | 数据加载态 | 无（原型未展示，实现时用） |
| `PostMarketReview` | 复盘 Tab 内容 | 改受控 `date` prop + 删内部 date picker + 移出 WeatherDecisionBar |
| `PreMarketBriefing` | 当日 Tab 内容 | 改受控 `date` prop + 拆出 PremarketSelectionSection |
| `PremarketSelectionSection` | 前瞻 Tab 内容 | 接口不变，调用方传 dateTriplet.forward |
| `ShadowComparisonSection`（S050） | 当日 Tab ④ 区 | 无 |
| `WeatherDecisionBar`（S063） | 当日 Tab 顶部 | 从 PostMarketReview 移入 |
| 暴风雨预测（S088） | 当日 Tab ⑤ 区 | 无 |

### 5.2 新建组件

| 组件 | 职责 | 对应 spec R |
|---|---|---|
| `AnchorBar` | 锚条：F + 三视图数据日 + 时段标签 | R1/R3/R9 |
| `TaskStatusCard` | 任务状态卡片：时间线 + 状态色 + 载入按钮 + 折叠 | R16/R17/R18 |
| `TaskTimelineItem` | 单个任务节点（圆点 + 时间 + 名称 + 状态 + 载入） | R16 |
| `PlaceholderCard` | "待 {cron时间} 产出"虚线占位卡 | R3a |
| `CollectingBanner` | 前瞻 Tab"采集中"大号占位 | R3b |
| `useDateTriplet` | hook：调 `GET /api/workflow/date-triplet` | R13 |
| `useMarketClock` | hook：双定时器 + 过渡窗 60s 轮询 | R14 |
| `useScheduledTasksStatus` | hook：调 `GET /api/scheduled-tasks`，过渡窗轮询 | R16/R18 |

---

## 6. 响应式考虑

原型在 `@media (max-width: 720px)` 下做了以下适配：

| 区域 | 桌面 | 移动 |
|---|---|---|
| AnchorBar | 三栏 grid（F | 三视图 | 时段） | 单列堆叠，三视图数据日左对齐 |
| TaskStatusCard 时间线 | `1fr auto auto`（名称+ETA+按钮） | `1fr auto`，隐藏 ETA |
| MetricCard 网格 | `auto-fill minmax(150px, 1fr)` | `repeat(2, 1fr)` 固定两列 |
| 候选标的行 | `auto 1fr auto auto`（排名+名称+得分+价格） | `auto 1fr auto`，隐藏价格列 |
| TabBar | 横向三 Tab | 横向三 Tab（宽度足够，无需滚动） |

**未在原型中展示但实现时需注意**：
- 复盘 Tab 的 ② 占位区在窄屏从 `repeat(auto-fill, 200px)` 变单列
- 当日 Tab 的行为对照卡双栏在窄屏堆叠为单列
- 非交易日边界：任务卡片显示"非交易日，无采集任务"单行提示，定时器跳过

---

## 7. 原型使用说明

浏览器直接打开 `ui-prototype.html`。

顶部 sticky 切换器可对比两个时段：
- **盘后过渡窗 15:00-17:15**：复盘 Tab 高亮、任务卡片展开（4 done / 1 running / 3 pending）、前瞻显示"采集中"占位
- **盘后就绪 17:15+**：前瞻 Tab 高亮、任务卡片折叠为摘要条（8/8 done）、三视图数据完整

点击 Tab 切换视图；点击任务项展开详情；done 任务项的"载入"按钮可点击（模拟 refetch）。
