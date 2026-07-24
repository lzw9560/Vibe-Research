import {
  Cog, Cpu, Database, Cable, Rocket, FlaskConical, Clock, TrendingUp, BarChart3,
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

// 板块中心子链接
export const SECTOR_LINKS = [
  { to: "/sectors/humanoid", icon: Cog, label: "人形机器人" },
  { to: "/sectors/ai-computing", icon: Cpu, label: "AI 算力" },
  { to: "/sectors/hbm", icon: Database, label: "HBM" },
  { to: "/sectors/cpo", icon: Cable, label: "光互联" },
  { to: "/sectors/business-space", icon: Rocket, label: "商业航天" },
  { to: "/sectors/ai-pharma", icon: FlaskConical, label: "生物医药" },
];

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

// 打板工作流阶段配置
export const WORKFLOW_STAGES = [
  {
    key: "pre-market" as const,
    label: "盘前简报",
    timeRange: "08:00 - 09:30",
    icon: Clock,
    color: "text-blue-400",
    bg: "bg-blue-500/10 border-blue-500/30",
    description: "候选池筛选 → 战法匹配 → 仓位建议",
    steps: ["候选池筛选", "战法匹配", "仓位建议", "推送准备"],
    quickLinks: [
      { to: "/workflow/pre-market", label: "盘前简报" },
      { to: "/limitup/gene", label: "基因选股" },
      { to: "/limitup/auction", label: "竞价预案" },
    ],
  },
  {
    key: "intraday" as const,
    label: "盘中监控",
    timeRange: "09:30 - 15:00",
    icon: TrendingUp,
    color: "text-green-400",
    bg: "bg-green-500/10 border-green-500/30",
    description: "实时监控 → 炸板预警 → 动态调仓",
    steps: ["实时监控", "炸板预警", "动态调仓", "止盈止损"],
    quickLinks: [
      { to: "/workflow/intraday", label: "盘中监控" },
      { to: "/workflow/alerts", label: "炸板预警" },
      { to: "/sentiment/weather", label: "情绪气象" },
      { to: "/limitup/seats", label: "席位引擎" },
    ],
  },
  {
    key: "post-market" as const,
    label: "盘后复盘",
    timeRange: "15:00 - 22:00",
    icon: BarChart3,
    color: "text-purple-400",
    bg: "bg-purple-500/10 border-purple-500/30",
    description: "自动结算 → LLM复盘 → 胜率更新",
    steps: ["自动结算", "LLM复盘", "胜率更新", "参数优化"],
    quickLinks: [
      { to: "/workflow/post-market", label: "盘后复盘" },
      { to: "/daily-review", label: "每日复盘" },
      { to: "/metrics", label: "性能监控" },
    ],
  },
];

// 移动端次级 Tab 配置（按路径前缀匹配）
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
};
