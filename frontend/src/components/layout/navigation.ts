import {
  Cog, Cpu, Database, Cable, Rocket, FlaskConical,
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
