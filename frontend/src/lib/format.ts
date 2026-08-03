// lib/format.ts — 百分比格式化公共函数（S025-B 去重复 + 消量纲歧义）。
// 两个函数名揭示入参量纲，避免 100× 混淆：
//   - formatRate：入参是分数（0.6 表示 60%），需 ×100。
//   - formatPercent：入参已是百分数（1.5 表示 1.5%），仅格式化 + 追加 %。
// 消费方：winrate StatsMetrics + BreakdownTable。
//
// 注意量纲歧义：winrate 的 avg_return/max_drawdown 走 formatPercent（已是百分数，
// 如 1.5 = 1.5%）；而 Backtest 页的同名字段是分数（0.015 = 1.5%，走 ×100）。
// 同名字段相反量纲是真实隐患——选错函数即 100× 偏差，故每处须按入参是分数还是百分数选对函数。

/**
 * 分数 → 百分比字符串：0.6 → "60.0%"，-0.05 → "-5.0%"。
 * 入参是小数分数，乘 100 后保留 1 位小数。用于 win_rate 等分数型字段。
 */
export function formatRate(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

/**
 * 百分数 → 百分比字符串：1.5 → "1.50%"，-8.2 → "-8.20%"。
 * 入参已是百分数（如 1.5 表示 1.5%），仅保留 2 位小数 + 追加 %。
 * 用于 winrate 的 avg_return/max_drawdown（值域已是百分数）。
 */
export function formatPercent(v: number): string {
  return `${v.toFixed(2)}%`;
}
