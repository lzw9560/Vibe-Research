// S013 T8：TanStack Query hooks 统一出口。按域分文件（market/stock/limitup），
// 此处 barrel re-export，页面经 `import { useX } from "@/lib/query"` 取用。
// 写操作（POST/PUT/DELETE）未包——留直接调用或后续 useMutation。
export * from "./market";
export * from "./stock";
export * from "./limitup";
export * from "./topology";
export * from "./workflow";
export * from "./winrate";  // S050 W0：影子对照
export * from "./intraday";  // S063：盘中情绪辅助决策
export * from "./coach";  // S064：盯盘教练
export * from "./journal";  // S149 P3：交易日志 + 个人风控
export type { Opts } from "./types";
