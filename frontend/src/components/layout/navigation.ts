import {
  LayoutDashboard, Filter, TrendingUp, PieChart, BookOpen,
  Settings,
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

// S186 Phase 2: 6 域 19 tab（7 组 41 tab → 6 域 19 tab，减 54%）
// 旧散页 redirect 保兼容（router.tsx），nav 只保留 6 域主入口
export const NAV_GROUPS: NavGroup[] = [
  {
    name: "看盘",
    icon: LayoutDashboard,
    tabs: [
      { to: "/market", label: "市场全景" },
      { to: "/intraday", label: "盘中 cockpit" },
      { to: "/workflow/intraday/ofi", label: "资金流看板" },
      { to: "/sentiment/weather", label: "情绪气象" },
      { to: "/sectors/:key", label: "板块" },
    ],
  },
  {
    name: "选股",
    icon: Filter,
    tabs: [
      { to: "/screener", label: "选股器" },
      { to: "/bidding", label: "竞价监控" },
      { to: "/limitup", label: "打板策略" },
      { to: "/limitup/premarket", label: "盘前选股" },
      { to: "/watchlist", label: "自选股" },
    ],
  },
  {
    name: "个股",
    icon: TrendingUp,
    tabs: [
      { to: "/multiline", label: "多策略总览" },
      { to: "/strategy", label: "策略验证" },
      { to: "/fusion", label: "融合研判" },
    ],
  },
  {
    name: "模拟盘",
    icon: PieChart,
    tabs: [
      { to: "/journal", label: "交易日志" },
      { to: "/portfolio", label: "组合" },
      { to: "/risk", label: "风险看板" },
      { to: "/advisory", label: "建议中心" },
    ],
  },
  {
    name: "复盘",
    icon: BookOpen,
    tabs: [
      { to: "/review", label: "复盘中心" },
      { to: "/topology", label: "拓扑图" },
      { to: "/industry", label: "行业研究" },
    ],
  },
  {
    name: "系统",
    icon: Settings,
    tabs: [
      { to: "/settings", label: "设置" },
      { to: "/chat", label: "AI 对话" },
      { to: "/scheduled-tasks", label: "定时任务" },
      { to: "/pipeline", label: "流程管线" },
      { to: "/architecture", label: "项目架构" },
      { to: "/health", label: "系统健康" },
      { to: "/metrics", label: "指标分析" },
    ],
  },
];

// Phase 0 手风琴默认展开组（S179 R0.5：单组展开，Layout.tsx 消费）
export const DEFAULT_EXPANDED_GROUP = "看盘";
