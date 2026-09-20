import {
  Clock, LayoutDashboard, FlaskConical, Network, Database, Settings,
} from "lucide-react";

export interface NavTab {
  to: string;
  label: string;
}

export interface NavSubGroup {
  name: string;
  tabs: NavTab[];
}

export interface NavGroup {
  name: string;
  icon: React.ComponentType<{ className?: string }>;
  hub: NavTab;  // 线主入口（1 跳直达，collapsible 标题点击也跳 hub）
  subGroups: NavSubGroup[];  // 子组（collapsible 展开）
  matchPrefix: string[];  // 活跃线匹配的路由前缀（详情页也能高亮归属线）
}

// 主题选项
export const THEMES = [
  { key: "dark" as const, emoji: "🌙", label: "暗色" },
  { key: "light" as const, emoji: "☀️", label: "亮色" },
  { key: "warm-orange" as const, emoji: "🔥", label: "暖橙" },
] as const;

export const APP_VERSION = "v0.3.0";
export const REPO_URL = "https://github.com/lzw9560/Vibe-Research";
export const CONTACT_HANDLE = "lzw9560";

// 5 线 IA + 系统（子组嵌套 collapsible，活跃线自动展开）
// Phase 2（2026-09-21）：UX agent 方案 A 重做——子组嵌套代替扁平
// 归组修正（grill）：/recommendation MultiArm 非打板→盘面·打板；/intel 市场资讯→盘面·资讯；
// /portfolio 投资管理非日志→复盘·持仓日志；运维留系统·运维子组（非并入数据层）
export const NAV_GROUPS: NavGroup[] = [
  {
    name: "今日",
    icon: Clock,
    hub: { to: "/today", label: "今日" },
    subGroups: [
      { name: "前瞻·环境", tabs: [
        { to: "/prediction", label: "前瞻" },
        { to: "/sentiment/weather", label: "情绪气象" },
        { to: "/earnings-calendar", label: "财报季" },
      ]},
    ],
    matchPrefix: ["/today", "/prediction", "/sentiment/weather", "/earnings-calendar"],
  },
  {
    name: "盘面",
    icon: LayoutDashboard,
    hub: { to: "/workspace", label: "盘面" },
    subGroups: [
      { name: "市场全景", tabs: [
        { to: "/market", label: "市场全景" },
        { to: "/intraday", label: "盘中 cockpit" },
      ]},
      { name: "选股·漏斗", tabs: [
        { to: "/screener", label: "选股器" },
        { to: "/candidates", label: "候选池" },
        { to: "/value-funnel", label: "选股漏斗" },
      ]},
      { name: "自选·竞价", tabs: [
        { to: "/watchlist", label: "自选股" },
        { to: "/bidding", label: "竞价监控" },
      ]},
      { name: "打板", tabs: [
        { to: "/limitup", label: "打板策略" },
        { to: "/limitup/premarket", label: "盘前选股" },
        { to: "/recommendation", label: "今日建议" },
      ]},
      { name: "资讯", tabs: [
        { to: "/intel", label: "资讯雷达" },
        { to: "/stock-data", label: "股票数据" },
      ]},
    ],
    matchPrefix: ["/workspace", "/market", "/intraday", "/screener", "/candidates", "/value-funnel", "/watchlist", "/bidding", "/limitup", "/recommendation", "/intel", "/stock-data", "/stock/", "/sectors/"],
  },
  {
    name: "复盘",
    icon: FlaskConical,
    hub: { to: "/review", label: "复盘" },
    subGroups: [
      { name: "持仓·日志", tabs: [
        { to: "/ledger", label: "持仓日志" },
        { to: "/journal", label: "交易日志" },
        { to: "/portfolio", label: "投资管理" },
      ]},
      { name: "策略工作台", tabs: [
        { to: "/strategy", label: "策略验证" },
        { to: "/multiline", label: "多策略总览" },
      ]},
      { name: "研判·风险", tabs: [
        { to: "/fusion", label: "融合研判" },
        { to: "/risk", label: "风险看板" },
        { to: "/advisory", label: "AI 顾问" },
      ]},
      { name: "拓扑·跟踪", tabs: [
        { to: "/topology", label: "拓扑图" },
        { to: "/industry", label: "行业研究" },
        { to: "/tracking", label: "多日跟踪" },
      ]},
    ],
    matchPrefix: ["/review", "/ledger", "/journal", "/portfolio", "/strategy", "/multiline", "/fusion", "/risk", "/advisory", "/topology", "/industry", "/tracking", "/workflow/candidates", "/workflow/factor", "/strategy/funnel"],
  },
  {
    name: "图谱",
    icon: Network,
    hub: { to: "/graph", label: "图谱" },
    subGroups: [
      { name: "量化模型", tabs: [
        { to: "/quant-models", label: "量化模型" },
        { to: "/debate", label: "多空辩论" },
      ]},
    ],
    matchPrefix: ["/graph", "/quant-models", "/debate"],
  },
  {
    name: "数据层",
    icon: Database,
    hub: { to: "/data", label: "数据层" },
    subGroups: [
      { name: "数据运维", tabs: [
        { to: "/workflow/intraday/ofi", label: "OFI 看板" },
      ]},
    ],
    matchPrefix: ["/data", "/workflow/intraday/ofi"],
  },
  {
    name: "系统",
    icon: Settings,
    hub: { to: "/settings", label: "系统" },
    subGroups: [
      { name: "配置", tabs: [
        { to: "/chat", label: "AI 对话" },
        { to: "/scheduled-tasks", label: "定时任务" },
      ]},
      { name: "运维", tabs: [
        { to: "/pipeline", label: "流程管线" },
        { to: "/architecture", label: "项目架构" },
        { to: "/health", label: "系统健康" },
        { to: "/metrics", label: "采集指标" },
      ]},
    ],
    matchPrefix: ["/settings", "/chat", "/scheduled-tasks", "/pipeline", "/architecture", "/health", "/metrics"],
  },
];
