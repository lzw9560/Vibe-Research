// 工作流七态共享元数据（S033）：色板 + 中文标签 + 8 大战法名。
// 色板为决策锁定项（spec §5 R5）：candidate=蓝 / watching=黄 / monitoring=橙 /
// holding=绿 / settled=灰 / filtered=红淡 / pending=灰淡。
export const STATUS_COLORS: Record<string, string> = {
  candidate: "bg-blue-500",
  watching: "bg-yellow-500",
  monitoring: "bg-orange-500",
  holding: "bg-green-500",
  settled: "bg-gray-400",
  filtered: "bg-red-300",
  pending: "bg-gray-200",
};

export const STATUS_LABELS: Record<string, string> = {
  pending: "待选",
  candidate: "候选",
  watching: "观察",
  monitoring: "监控",
  holding: "持仓",
  settled: "已结算",
  filtered: "已过滤",
};

/** 8 大战法名（limitup_strategy.STRATEGY_REGISTRY，名称不变，硬编码省一次请求——S033 决策 ⑤）。 */
export const STRATEGY_NAMES: string[] = [
  "首板挖掘",
  "连板接力",
  "炸板回封",
  "低吸龙头",
  "反包战法",
  "N字反击",
  "平台突破",
  "尾盘偷袭",
];
