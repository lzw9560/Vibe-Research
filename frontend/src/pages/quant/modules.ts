// Track D M3: 量化系统 M1-M7 模块定义（S200 方法论）。
// 单一真相源：QuantModelsPage 渲染 7 卡。诚实标注 live/planning——不臆造数据。
// live = 后端已实现（有 endpoint 的显 live 数据徽章，无的标"前端待接线"）；planning = spec-only/未实现。
export type ModuleStatus = "live" | "planning";

export interface QuantModule {
  key: string;        // "M1".."M7"
  title: string;
  subtitle: string;
  status: ModuleStatus;
  note: string;       // 诚实描述（实现状态/边界）
  link?: string;      // 路由（live 且有页面时）
  /** live 卡尝试拉的真实数据源；null=无前端 endpoint（标"数据待接线"） */
  liveSource?: "ofi" | "expectationGap" | "emHealth" | "earningsCalendar" | "kgInbox" | null;
}

export const QUANT_MODULES: readonly QuantModule[] = [
  {
    key: "M1",
    title: "OFI 订单流不平衡",
    subtitle: "盘中买盘/卖盘力量归一化看板",
    status: "live",
    note: "GET /api/intraday/ofi 只读看板（S178）。归一化 OFI ∈ [-1,1]，非交易信号。",
    link: "/workflow/intraday/ofi",
    liveSource: "ofi",
  },
  {
    key: "M2",
    title: "预期差",
    subtitle: "公告/财报预期差度量",
    status: "live",
    note: "GET /api/expectation-gap（S216 P2）。T-1 close + T open 差（高开%）+ 量比代理，复用 S205 compute_expectation_gap_reversal。",
    liveSource: "expectationGap",
  },
  {
    key: "M3",
    title: "CentralRouter 内部撮合",
    subtitle: "替代席位名臆测的内部撮合路由",
    status: "planning",
    note: "spec-only/未实现。规划用 CentralRouter 内部撮合替代席位名归因（防席位名失真）。",
  },
  {
    key: "M4",
    title: "em_get 防封",
    subtitle: "东财端点限流/熔断/代理探测",
    status: "live",
    note: "GET /api/transport/em-health（S216 P2）。circuit_breaker 各 breaker 状态（state + failure_count），em_get 防封底线。",
    liveSource: "emHealth",
  },
  {
    key: "M5",
    title: "财报季排雷",
    subtitle: "ReportSeasonCircuitBreaker 1/4/8月雷区",
    status: "live",
    note: "GET /api/earnings-calendar（S216 P2 + S225 M5）。DANGER_MONTHS 1/4/8 + is_earnings_season_unsafe 拉黑未披露，arm 跳过防一字跌停。",
    liveSource: "earningsCalendar",
  },
  {
    key: "M6",
    title: "国家队护盘",
    subtitle: "跌破整数关口权重股护盘先验",
    status: "planning",
    note: "spec-only/未实现。跌破整数关口时权重股护盘函数（日历效应先验）。",
  },
  {
    key: "M7",
    title: "LLM 图谱智能体",
    subtitle: "DeepSeek 公告→JSON→图谱注入",
    status: "live",
    note: "GET /api/kg/inbox + POST /api/kg/inject + /api/kg/approve（S226 M7）。公告→DeepSeek JSON→inbox 待审→reference 注入流已通电，/graph 审核闭环。",
    link: "/graph",
    liveSource: "kgInbox",
  },
] as const;
