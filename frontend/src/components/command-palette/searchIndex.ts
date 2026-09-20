// S179 P0.2: 命令面板搜索索引——路由名 + 股票代码(stub) + 预设信号 + 模糊匹配。
// 路由索引从 navigation.ts NAV_GROUPS 提取（fresh grep 确认 5 组 35 tabs）。
// 股票代码为前端 stub（15 支知名 A 股），完整 ~5300 代码表数据源待核实（见 notes）。

import { NAV_GROUPS } from "@/components/layout/navigation";

export type SearchGroup = "route" | "stock" | "signal" | "research";

export type SearchAction =
  | { type: "navigate"; path: string }
  | { type: "select-stock"; code: string; name: string }
  | { type: "apply-preset"; path: string; preset: string };

export interface SearchItem {
  id: string;
  title: string;
  subtitle: string;
  group: SearchGroup;
  keywords: string[];
  action: SearchAction;
}

// ── 路由索引：从 NAV_GROUPS hub + subGroups 提取 {label, path} ──────────────
const ROUTE_INDEX: SearchItem[] = NAV_GROUPS.flatMap((group) =>
  [group.hub, ...group.subGroups.flatMap(sg => sg.tabs)].map((tab) => ({
    id: `route:${tab.to}`,
    title: tab.label,
    subtitle: tab.to,
    group: "route" as const,
    keywords: [group.name, tab.to.replace(/\//g, " ")],
    action: { type: "navigate" as const, path: tab.to },
  })),
);

// ── 股票代码索引（stub，待核实） ────────────────────────────────────────────
// 完整 A 股 ~5300 代码表数据源待核实（前端内置 ~200KB vs 后端搜索 API）。
// 先 stub 15 支知名 A 股验证交互，数据源确定后替换为完整代码表或动态 API。
const STOCK_STUB: { code: string; name: string }[] = [
  { code: "600519", name: "贵州茅台" },
  { code: "000858", name: "五粮液" },
  { code: "601318", name: "中国平安" },
  { code: "600036", name: "招商银行" },
  { code: "000333", name: "美的集团" },
  { code: "601166", name: "兴业银行" },
  { code: "002594", name: "比亚迪" },
  { code: "600276", name: "恒瑞医药" },
  { code: "000651", name: "格力电器" },
  { code: "601398", name: "工商银行" },
  { code: "600887", name: "伊利股份" },
  { code: "000725", name: "京东方A" },
  { code: "300750", name: "宁德时代" },
  { code: "600030", name: "中信证券" },
  { code: "002475", name: "立讯精密" },
];

const STOCK_INDEX: SearchItem[] = STOCK_STUB.map((s) => ({
  id: `stock:${s.code}`,
  title: `${s.code} ${s.name}`,
  subtitle: s.code,
  group: "stock" as const,
  keywords: [s.name, s.code],
  action: { type: "select-stock" as const, code: s.code, name: s.name },
}));

// ── 预设信号索引 ─────────────────────────────────────────────────────────────
// Phase 0 指向现有 limitup 子路由；Phase 1 /screener 建成后改为 ?preset=xxx。
const SIGNAL_PRESETS: { name: string; path: string; preset: string; aliases: string[] }[] = [
  { name: "突破信号", path: "/limitup/premarket", preset: "breakout", aliases: ["breakout", "突破"] },
  { name: "基因筛选", path: "/limitup/gene", preset: "gene", aliases: ["gene", "基因"] },
  { name: "竞价选股", path: "/limitup/auction", preset: "auction", aliases: ["auction", "竞价"] },
  { name: "席位引擎", path: "/limitup/seats", preset: "seats", aliases: ["seats", "席位"] },
  { name: "打板策略", path: "/limitup", preset: "limitup", aliases: ["limitup", "打板", "涨停"] },
];

const SIGNAL_INDEX: SearchItem[] = SIGNAL_PRESETS.map((s) => ({
  id: `signal:${s.preset}`,
  title: s.name,
  subtitle: `预设信号 → ${s.path}`,
  group: "signal" as const,
  keywords: s.aliases,
  action: { type: "apply-preset" as const, path: s.path, preset: s.preset },
}));

// ── 研究深挖索引（Track D M2）─────────────────────────────────────────────
// 骨干全可达不进主导航：战法/因子/量化模型/图谱/数据 经 palette lazy-load（code-split）。
// 主导航保 5（今日/盘面/复盘/图谱/数据层）；图谱/数据在此亦列便于键盘直达。
const RESEARCH_PRESETS: { name: string; path: string; aliases: string[] }[] = [
  { name: "战法", path: "/strategy", aliases: ["战法", "策略", "strategy", "回测"] },
  { name: "因子", path: "/review?tab=validation", aliases: ["因子", "验证", "§44", "factor", "verdict"] },
  { name: "量化模型", path: "/quant-models", aliases: ["量化模型", "M1", "M7", "OFI", "quant"] },
  { name: "图谱", path: "/graph", aliases: ["图谱", "认知", "M7", "graph", "公告"] },
  { name: "数据", path: "/data", aliases: ["数据", "数据层", "采集", "data", "backfill"] },
  { name: "财报季", path: "/earnings-calendar", aliases: ["财报季", "财报日历", "雷区", "披露", "earnings", "M5"] },
];

const RESEARCH_INDEX: SearchItem[] = RESEARCH_PRESETS.map((s) => ({
  id: `research:${s.path}`,
  title: s.name,
  subtitle: `研究深挖 → ${s.path}`,
  group: "research" as const,
  keywords: s.aliases,
  action: { type: "navigate" as const, path: s.path },
}));

// ── 合并索引 ─────────────────────────────────────────────────────────────────
export const SEARCH_INDEX: SearchItem[] = [...ROUTE_INDEX, ...STOCK_INDEX, ...SIGNAL_INDEX, ...RESEARCH_INDEX];

// ── 模糊匹配 ─────────────────────────────────────────────────────────────────
/** 子序列匹配 + 评分：连续匹配加分、起始匹配加分。返回 0 = 不匹配。 */
function subsequenceScore(query: string, target: string): number {
  let qi = 0;
  let score = 0;
  let consecutive = 0;
  for (let ti = 0; ti < target.length && qi < query.length; ti++) {
    if (target[ti] === query[qi]) {
      qi++;
      consecutive++;
      score += consecutive * 2;
      if (ti === 0) score += 10;
    } else {
      consecutive = 0;
    }
  }
  return qi === query.length ? score : 0;
}

/** 对单个 item 评分：0 = 不匹配，>0 = 匹配（越高越好）。 */
export function fuzzyMatch(query: string, item: SearchItem): number {
  const q = query.toLowerCase().trim();
  if (!q) return 1;

  const title = item.title.toLowerCase();
  const subtitle = item.subtitle.toLowerCase();

  if (title === q) return 200;
  if (subtitle === q) return 190;
  if (title.startsWith(q)) return 150;
  if (subtitle.startsWith(q)) return 140;

  const titleScore = subsequenceScore(q, title);
  if (titleScore > 0) return titleScore + 80;

  const subScore = subsequenceScore(q, subtitle);
  if (subScore > 0) return subScore + 60;

  for (const kw of item.keywords) {
    const kl = kw.toLowerCase();
    if (kl === q) return 120;
    if (kl.startsWith(q)) return 100;
    const kwScore = subsequenceScore(q, kl);
    if (kwScore > 0) return kwScore + 40;
  }

  return 0;
}

/** 搜索全索引，返回按评分降序排列的 top N 结果。 */
export function searchAll(query: string, limit = 12): SearchItem[] {
  return SEARCH_INDEX
    .map((item) => ({ item, score: fuzzyMatch(query, item) }))
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((r) => r.item);
}
