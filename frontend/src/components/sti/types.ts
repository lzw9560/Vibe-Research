// STI API 类型定义

// 八维指标
export interface STIDimension {
  limit_up_count: number;
  limit_down_count: number;
  seal_rate: number;
  advance_decline_ratio: number;
  promotion_rate: number;
  prev_zt_performance: number;
  max_boards: number;
  market_factor: number;
}

// STI 结果
export interface STIResult {
  date: string;
  score: number | null;
  phase: "高潮" | "启动" | "分歧" | "冰点" | "退潮" | null;
  dimensions: STIDimension | null;
  source_ok: boolean;
  confidence: string;  // "high" | "medium" | "low"
  change_from_yesterday: number | null;
  data_updated: string | null;
  phase_explanation: string | null;
  disclaimer: string;
}

// STI 时间线条目
export interface STITimelineItem {
  date: string;
  score: number | null;
  phase: string | null;
  change_from_yesterday: number | null;
}

// 权重配置
export const STI_WEIGHTS: Record<string, number> = {
  "limit_up_count": 0.15,
  "limit_down_count": 0.13,
  "seal_rate": 0.25,
  "advance_decline_ratio": 0.10,
  "promotion_rate": 0.22,
  "prev_zt_performance": 0.10,
  "max_boards": 0.05,
};

// 维度标签映射
export const DIMENSION_LABELS: Record<string, string> = {
  "limit_up_count": "涨停家数",
  "limit_down_count": "跌停家数",
  "seal_rate": "封板率",
  "advance_decline_ratio": "涨跌比",
  "promotion_rate": "晋级率",
  "prev_zt_performance": "昨日涨停表现",
  "max_boards": "连板高度",
};

// 阶段颜色
export const PHASE_COLORS: Record<string, string> = {
  "高潮": "text-danger",
  "启动": "text-primary",
  "分歧": "text-yellow-400",
  "冰点": "text-muted-foreground",
  "退潮": "text-purple-400",
};

// 阶段分数范围
export function getPhaseGradient(phase: string): string {
  switch (phase) {
    case "高潮": return "from-red-500/20 to-red-900/5";
    case "启动": return "from-orange-500/20 to-orange-900/5";
    case "分歧": return "from-yellow-500/20 to-yellow-900/5";
    case "冰点": return "from-gray-500/20 to-gray-900/5";
    case "退潮": return "from-purple-500/20 to-purple-900/5";
    default: return "from-gray-500/10 to-gray-900/5";
  }
}
