import {
  Home, LayoutDashboard, Settings,
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
export const APP_VERSION = "v0.3.0";
export const REPO_URL = "https://github.com/simonlin1212/Vibe-Research";
export const CONTACT_HANDLE = "lzw9560";

// 多维度 IA: 5 线主入口 + 数据层 + 系统折叠
// 今日(时间) / 盘面(选股) / 复盘(验证+策略 2 tab) / 图谱(认知) / 数据层
// 持仓日志移入旧页（策略线"模拟"步，经 CTA 脊访问）
export const NAV_GROUPS: NavGroup[] = [
  {
    name: "主入口",
    icon: Home,
    tabs: [
      { to: "/today", label: "今日" },
      { to: "/workspace", label: "盘面" },
      { to: "/review", label: "复盘" },
      { to: "/graph", label: "图谱" },
      { to: "/data", label: "数据层" },
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
      { to: "/metrics", label: "采集指标" },
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
      { to: "/candidates", label: "候选池" },
      { to: "/recommendation", label: "今日建议" },
      { to: "/value-funnel", label: "选股漏斗" },
      { to: "/watchlist", label: "自选股" },
      { to: "/limitup", label: "打板策略" },
      { to: "/limitup/premarket", label: "盘前选股" },
      { to: "/bidding", label: "竞价监控" },
    ],
  },
  {
    name: "个股·策略",
    icon: LayoutDashboard,
    tabs: [
      { to: "/ledger", label: "持仓日志" },
      { to: "/journal", label: "交易日志" },
      { to: "/multiline", label: "多策略总览" },
      { to: "/strategy", label: "策略验证" },
      { to: "/fusion", label: "融合研判" },
      { to: "/risk", label: "风险看板" },
      { to: "/advisory", label: "AI 顾问" },
    ],
  },
  {
    name: "复盘",
    icon: LayoutDashboard,
    tabs: [
      { to: "/topology", label: "拓扑图" },
      { to: "/industry", label: "行业研究" },
    ],
  },
];

// flat-5 rail: 5 主入口永久可见
export const DEFAULT_EXPANDED_GROUP = "主入口";
