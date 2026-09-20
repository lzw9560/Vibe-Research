import {
  Clock, LayoutDashboard, FlaskConical, Network, Database, Settings,
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
export const REPO_URL = "https://github.com/lzw9560/Vibe-Research";
export const CONTACT_HANDLE = "lzw9560";

// 5 线 IA + 系统（扁平结构：旧页 + 孤儿归进 5 线 tabs，系统含运维）
// Phase 1（2026-09-20）：合并 LEGACY_NAV_GROUPS 进 NAV_GROUPS 扁平化
// → searchIndex 自动覆盖 35 路由（Cmd+K 红利）+ 移动 drawer 全 reach
// 归组修正（grill）：/recommendation MultiArm 非打板→盘面；/intel 市场资讯→盘面；
// /portfolio 投资管理非日志→复盘；运维留系统组（非并入数据层，系统健康是系统级）
export const NAV_GROUPS: NavGroup[] = [
  {
    name: "今日",
    icon: Clock,
    tabs: [
      { to: "/today", label: "今日" },
      { to: "/prediction", label: "前瞻" },
      { to: "/sentiment/weather", label: "情绪气象" },
      { to: "/earnings-calendar", label: "财报季" },
    ],
  },
  {
    name: "盘面",
    icon: LayoutDashboard,
    tabs: [
      { to: "/workspace", label: "盘面" },
      { to: "/market", label: "市场全景" },
      { to: "/intraday", label: "盘中 cockpit" },
      { to: "/screener", label: "选股器" },
      { to: "/candidates", label: "候选池" },
      { to: "/value-funnel", label: "选股漏斗" },
      { to: "/watchlist", label: "自选股" },
      { to: "/bidding", label: "竞价监控" },
      { to: "/limitup", label: "打板策略" },
      { to: "/limitup/premarket", label: "盘前选股" },
      { to: "/recommendation", label: "今日建议" },
      { to: "/intel", label: "资讯雷达" },
      { to: "/stock-data", label: "股票数据" },
    ],
  },
  {
    name: "复盘",
    icon: FlaskConical,
    tabs: [
      { to: "/review", label: "复盘" },
      { to: "/ledger", label: "持仓日志" },
      { to: "/journal", label: "交易日志" },
      { to: "/portfolio", label: "投资管理" },
      { to: "/multiline", label: "多策略总览" },
      { to: "/strategy", label: "策略验证" },
      { to: "/fusion", label: "融合研判" },
      { to: "/risk", label: "风险看板" },
      { to: "/advisory", label: "AI 顾问" },
      { to: "/topology", label: "拓扑图" },
      { to: "/industry", label: "行业研究" },
      { to: "/tracking", label: "多日跟踪" },
    ],
  },
  {
    name: "图谱",
    icon: Network,
    tabs: [
      { to: "/graph", label: "图谱" },
      { to: "/quant-models", label: "量化模型" },
      { to: "/debate", label: "多空辩论" },
    ],
  },
  {
    name: "数据层",
    icon: Database,
    tabs: [
      { to: "/data", label: "数据层" },
      { to: "/workflow/intraday/ofi", label: "OFI 看板" },
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
