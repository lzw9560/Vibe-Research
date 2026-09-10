import {
  LayoutDashboard, Filter, TrendingUp, PieChart, BookOpen,
  Microscope, Settings,
} from "lucide-react";

export interface NavGroup {
  name: string;
  icon: React.ComponentType<{ className?: string }>;
  tabs: NavTab[];
}

export interface NavTab {
  to: string;
  label: string;
}

// 主题选项
export const THEMES = [
  { key: "dark" as const, emoji: "🌙", label: "暗色" },
  { key: "light" as const, emoji: "☀️", label: "亮色" },
  { key: "warm-orange" as const, emoji: "🔥", label: "暖橙" },
] as const;

// 底部信息
export const APP_VERSION = "v0.1.3";
export const REPO_URL = "https://github.com/simonlin1212/Vibe-Research";
export const CONTACT_HANDLE = "lzw9560";

// 7 组导航（S179 R0.5 Phase 0 重组）
// 5 组 35 tab → 7 组 35 tab（不加新路由，只重组分组 + tab 归属）
// 新路由（/market /screener 等）Phase 1 建后才加入，避免死链（grill F3）
// tab 归属按 spec §11.3 映射草
// "复盘"组从"投资管理"拆出为 Phase 0 中间态（§11.3 终态合回 /review，Phase 3 精化）
export const NAV_GROUPS: NavGroup[] = [
  {
    name: "交易台",
    icon: LayoutDashboard,
    tabs: [
      // §11.3 → /market（daily-review + intel + sectors + sector-divergence + prediction + debate）
      { to: "/daily-review", label: "每日复盘" },
      { to: "/intel", label: "全球情报" },
      { to: "/sectors", label: "板块中心" },
      { to: "/sector-divergence", label: "板块分化" },
      { to: "/prediction", label: "涨跌预测" },
      { to: "/debate", label: "多空辩论" },
      // §11.3 → /intraday（workflow 盘中）
      { to: "/workflow", label: "工作流" },
    ],
  },
  {
    name: "选股",
    icon: Filter,
    tabs: [
      // §11.3 → /screener（candidates + value-funnel + limitup 5 子 + stock-data）
      { to: "/candidates", label: "候选池" },
      { to: "/value-funnel", label: "价值漏斗" },
      { to: "/limitup", label: "打板策略" },
      { to: "/limitup/gene", label: "基因筛选" },
      { to: "/limitup/auction", label: "竞价选股" },
      { to: "/limitup/seats", label: "席位引擎" },
      { to: "/limitup/premarket", label: "盘前选股" },
      { to: "/stock-data", label: "股票数据" },
      // §11.3 → /watchlist
      { to: "/watchlist", label: "自选股" },
    ],
  },
  {
    name: "个股",
    icon: TrendingUp,
    tabs: [
      // §11.3 → /strategy（strategy + backtest + strategy-signals + verifier-records + value-verdict）
      { to: "/strategy", label: "战法" },
      { to: "/backtest", label: "回测" },
      { to: "/strategy-signals", label: "策略信号" },
      { to: "/verifier-records", label: "§44 验证" },
      { to: "/value-verdict", label: "价值因子验证" },
    ],
  },
  {
    name: "投资管理",
    icon: PieChart,
    tabs: [
      // §11.3 → /portfolio（portfolio + risk-dashboard）
      { to: "/portfolio", label: "组合" },
      { to: "/risk-dashboard", label: "风险仪表盘" },
      // §11.3 → /advisory（advisory + recommendation）
      { to: "/advisory", label: "建议中心" },
      { to: "/recommendation", label: "推荐" },
      // §11.3 → /journal（journal + behavior-loop）
      { to: "/journal", label: "交易日志" },
      { to: "/behavior-loop", label: "行为闭环" },
    ],
  },
  {
    name: "复盘",
    icon: BookOpen,
    tabs: [
      // §11.3 → /review（my-reports + notes）
      // Phase 0 中间态从"投资管理"拆出；Phase 3 合回 /review
      { to: "/my-reports", label: "我的研报" },
      { to: "/notes", label: "笔记" },
    ],
  },
  {
    name: "研究中心",
    icon: Microscope,
    tabs: [
      // §11.3 → /sentiment/weather
      { to: "/sentiment/weather", label: "情绪气象" },
      // §11.3 → /industry
      { to: "/industry", label: "行业研究" },
    ],
  },
  {
    name: "系统",
    icon: Settings,
    tabs: [
      // §11.3 → /settings
      { to: "/settings", label: "设置" },
      // §11.3 → /scheduled-tasks
      { to: "/scheduled-tasks", label: "定时任务" },
      // §11.3 → /health
      { to: "/health", label: "系统健康" },
      // §11.3 → /metrics
      { to: "/metrics", label: "指标分析" },
    ],
  },
];

// Phase 0 手风琴默认展开组（S179 R0.5：单组展开，Layout.tsx 消费）
export const DEFAULT_EXPANDED_GROUP = "交易台";

// 移动端次级 Tab 配置（按路径前缀匹配）
// Phase 3 删（S179 R3.5：页内 TabBar 替代 pathname hack）
export const SUB_TABS: Record<string, { key: string; label: string; to?: string }[]> = {
  "/stock/": [
    { key: "overview", label: "概览" },
    { key: "gene", label: "基因" },
    { key: "capital", label: "资金" },
    { key: "ai", label: "AI 分析" },
  ],
  "/intel": [
    { key: "events", label: "事件概率" },
    { key: "announcements", label: "A股公告" },
    { key: "news", label: "公开新闻" },
    { key: "investment", label: "Investment News" },
  ],
  "/daily-review": [
    { key: "sectors", label: "板块热度" },
    { key: "zt-detail", label: "涨停明细" },
    { key: "auction-review", label: "竞价回顾" },
  ],
  "/sentiment/weather": [
    { to: "/sentiment/weather", key: "realtime", label: "实时天气" },
    { to: "/sentiment/weather/history", key: "history", label: "历史趋势" },
    { to: "/sentiment/weather/strategy", key: "strategy", label: "策略建议" },
    { to: "/sentiment/weather/fuse", key: "fuse", label: "熔断规则" },
  ],
  "/recommendation": [
    { key: "today", label: "今日推荐" },
    { key: "history", label: "历史记录" },
  ],
  "/strategy-signals": [
    { key: "active", label: "活跃信号" },
    { key: "history", label: "历史信号" },
  ],
  "/risk-dashboard": [
    { key: "overview", label: "风险概览" },
    { key: "list", label: "风险列表" },
  ],
  "/backtest": [
    { key: "result", label: "回测结果" },
    { key: "winrate", label: "胜率趋势" },
  ],
  "/workflow": [],  // S087：Workflow 内部 6-tab 自管（T-1/语境/盘前/盘中/盘后/战法），不渲染 Layout sub tab（避免 2 层 tab）
  "/metrics": [
    { key: "overview", label: "指标概览" },
    { key: "trends", label: "趋势分析" },
  ],
  "/health": [
    { key: "status", label: "健康状态" },
    { key: "logs", label: "运行日志" },
  ],
  "/scheduled-tasks": [
    { key: "active", label: "执行中" },
    { key: "history", label: "历史记录" },
  ],
  "/industry": [
    { key: "overview", label: "行业概览" },
    { key: "leaders", label: "龙头股" },
  ],
  "/sector-divergence": [
    { key: "divergence", label: "分化度" },
    { key: "rotation", label: "轮动速度" },
    { key: "history", label: "历史趋势" },
  ],
};
