import {
  Home, LayoutDashboard, Wallet, BookOpen, Settings,
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
export const APP_VERSION = "v0.2.0";
export const REPO_URL = "https://github.com/simonlin1212/Vibe-Research";
export const CONTACT_HANDLE = "lzw9560";

// Track B IA: 6域28tab → 4主入口 + 系统折叠
// 今日(动作队列) / 盘面(选股+盯盘合并+相位toggle) / 持仓日志(portfolio+journal+risk) / 复盘(review+strategy+topology+forward-test)
// 系统折叠: 设置/AI/定时/管线/架构/健康
export const NAV_GROUPS: NavGroup[] = [
  {
    name: "主入口",
    icon: Home,
    tabs: [
      { to: "/today", label: "今日" },
      { to: "/workspace", label: "盘面" },
      { to: "/ledger", label: "持仓日志" },
      { to: "/review", label: "复盘" },
    ],
  },
  {
    name: "系统",
    icon: Settings,
    tabs: [
      { to: "/settings", label: "设置" },
      { to: "/chat", label: "AI 对话" },
      { to: "/scheduled-tasks", label: "定时任务" },
      { to: "/pipeline", label: "任务健康" },
      { to: "/architecture", label: "项目架构" },
      { to: "/health", label: "系统健康" },
    ],
  },
];

// 旧 6 域兼容（旧页保留作详情页，新主入口链过去或嵌）
export const LEGACY_NAV_GROUPS: NavGroup[] = [
  {
    name: "看盘",
    icon: LayoutDashboard,
    tabs: [
      { to: "/market", label: "市场全景" },
      { to: "/intraday", label: "盘中 cockpit" },
      { to: "/prediction", label: "前瞻" },
      { to: "/sentiment/weather", label: "情绪气象" },
    ],
  },
  {
    name: "选股",
    icon: LayoutDashboard,
    tabs: [
      { to: "/screener", label: "选股器" },
      { to: "/value-funnel", label: "选股漏斗" },
      { to: "/watchlist", label: "自选股" },
      { to: "/limitup", label: "打板策略" },
      { to: "/limitup/premarket", label: "盘前选股" },
      { to: "/bidding", label: "竞价监控" },
    ],
  },
  {
    name: "个股",
    icon: LayoutDashboard,
    tabs: [
      { to: "/multiline", label: "多策略总览" },
      { to: "/strategy", label: "策略验证" },
      { to: "/fusion", label: "融合研判" },
    ],
  },
  {
    name: "持仓",
    icon: Wallet,
    tabs: [
      { to: "/portfolio", label: "组合" },
      { to: "/journal", label: "交易日志" },
      { to: "/risk", label: "风险看板" },
      { to: "/advisory", label: "建议中心" },
    ],
  },
  {
    name: "复盘",
    icon: BookOpen,
    tabs: [
      { to: "/topology", label: "拓扑图" },
      { to: "/industry", label: "行业研究" },
    ],
  },
];

// flat-4 rail: 不再用手风琴，4 主入口永久可见
export const DEFAULT_EXPANDED_GROUP = "主入口";
