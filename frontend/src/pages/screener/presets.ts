// S179 Phase 1: 选股器 preset 配置——5 个 preset 跳现有 /limitup/* 路由（非重建，grill #5）。
// grill #5 决策：选股器"统一"可能 6 页穿 trench coat——gene/auction/seats 独特交互。
// Phase 1 不强行统一 UI，preset 保留入口跳现有子页路由。
//
// 每个 preset = { id, name, path, aliases, description }。
// aliases 供 CommandPalette 搜索索引未来集成（当前仅按钮+下拉用 name+path）。

export interface ScreenerPreset {
  /** preset 唯一标识 */
  id: string;
  /** 显示名称 */
  name: string;
  /** 跳转路径（现有 /limitup/* 路由，非新建） */
  path: string;
  /** 搜索别名（CommandPalette 搜索索引未来用） */
  aliases: string[];
  /** preset 描述（tooltip + 下拉选项说明） */
  description: string;
}

export const SCREENER_PRESETS: readonly ScreenerPreset[] = [
  {
    id: "breakout",
    name: "突破选股",
    path: "/limitup/premarket",
    aliases: ["突破", "premarket", "盘前选股", "breakout"],
    description: "盘前突破信号选股（premarket_selection，breakout 因子）",
  },
  {
    id: "gene",
    name: "基因筛选",
    path: "/limitup/gene",
    aliases: ["基因", "涨停基因", "gene screener"],
    description: "涨停基因五因子评分筛选",
  },
  {
    id: "auction",
    name: "竞价选股",
    path: "/limitup/auction",
    aliases: ["竞价", "竞价选股", "auction"],
    description: "竞价预案 TOP N + 盘中 9:25 监控",
  },
  {
    id: "seats",
    name: "席位引擎",
    path: "/limitup/seats",
    aliases: ["席位", "席位引擎", "龙虎榜席位", "seats"],
    description: "龙虎榜席位资金流向引擎",
  },
  {
    id: "limitup",
    name: "打板策略",
    path: "/limitup",
    aliases: ["涨停", "打板", "涨停策略", "limitup"],
    description: "打板策略主页（涨停池 + 连板 + 情绪）",
  },
];
