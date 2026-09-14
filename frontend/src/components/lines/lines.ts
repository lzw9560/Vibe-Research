// 多维度 IA: 5 线定义——每线步骤环 + 状态计算 + nav 映射
// 单一真相源: 各线页、七灯、CTA 脊、PipelinePage fork 图均引用此定义
import type { LineStatus } from "@/components/lines/LineStatusLight";
import type { LoopStep } from "@/components/lines/LineLoopCard";

export type LineKey = "time" | "selection" | "validation" | "strategy" | "cognition";

export interface LineDef {
  key: LineKey;
  label: string;
  navLabel: string;
  path: string;
  subtitle: string;
  steps: LoopStep[];
  /** 横切线标记（风控/数据非用户线） */
  crossCutting?: boolean;
}

// 5 线步骤环——每线定义怎么走完一圈
export const LINES: readonly LineDef[] = [
  {
    key: "time",
    label: "时间",
    navLabel: "今日",
    path: "/today",
    subtitle: "盘前·盘中·盘后，时段感知驱动动作队列",
    steps: [
      { label: "盘前选股", link: "/workspace?phase=premarket" },
      { label: "竞价", link: "/bidding" },
      { label: "盘中盯盘", link: "/workspace?phase=intraday" },
      { label: "收盘复盘", link: "/review" },
      { label: "T+1备", link: "/today" },
    ],
  },
  {
    key: "selection",
    label: "选股",
    navLabel: "盘面",
    path: "/workspace",
    subtitle: "漏斗/竞价/席位/板块→候选→加自选→盯盘→信号→调参",
    steps: [
      { label: "漏斗", link: "/workspace?phase=premarket" },
      { label: "竞价", link: "/bidding" },
      { label: "席位/板块", link: "/market" },
      { label: "候选", link: "/screener" },
      { label: "加自选", link: "/watchlist" },
      { label: "盯盘", link: "/workspace?phase=intraday" },
      { label: "信号", link: "/workspace?phase=intraday" },
      { label: "调参", link: "/workspace?phase=premarket" },
    ],
  },
  {
    key: "validation",
    label: "验证",
    navLabel: "复盘·验证",
    path: "/review?tab=validation",
    subtitle: "因子→信号→§44 validated/待验证/证否→交易/记日志→调因子",
    steps: [
      { label: "因子", link: "/review?tab=validation" },
      { label: "信号验证态", link: "/review?tab=validation" },
      { label: "§44 verdict", link: "/review?tab=validation" },
      { label: "交易/记日志", link: "/ledger?tab=journal" },
      { label: "调因子", link: "/review?tab=validation" },
    ],
  },
  {
    key: "strategy",
    label: "策略",
    navLabel: "复盘·策略",
    path: "/review?tab=strategy",
    subtitle: "战法→回测§44→模拟→前向R3→复盘→调战法",
    steps: [
      { label: "战法", link: "/review?tab=strategy" },
      { label: "回测§44", link: "/review?tab=strategy" },
      { label: "模拟", link: "/ledger" },
      { label: "前向R3", link: "/review?tab=strategy" },
      { label: "复盘", link: "/review?tab=strategy" },
      { label: "调战法", link: "/review?tab=strategy" },
    ],
  },
  {
    key: "cognition",
    label: "认知",
    navLabel: "图谱",
    path: "/graph",
    subtitle: "M7 读公告→JSON→inbox 待审→reference→反哺策略→新信号",
    steps: [
      { label: "M7读公告", link: "/graph" },
      { label: "JSON注入", link: "/graph" },
      { label: "inbox待审", link: "/graph" },
      { label: "reference", link: "/graph" },
      { label: "反哺策略", link: "/review?tab=strategy" },
      { label: "新信号", link: "/review?tab=validation" },
    ],
  },
] as const;

// 横切线（非用户线，贯穿各线触发）
export interface CrossCuttingDef {
  key: "risk" | "data";
  label: string;
  navLabel: string;
  path: string;
  subtitle: string;
}

export const CROSS_CUTTING: readonly CrossCuttingDef[] = [
  {
    key: "risk",
    label: "风控横切",
    navLabel: "风控",
    path: "",  // 非页，徽章贯穿
    subtitle: "M4 断路器 / M5 财报季 / M6 日历——贯穿各线触发",
  },
  {
    key: "data",
    label: "数据底座",
    navLabel: "数据层",
    path: "/data",
    subtitle: "采集 / cache / backfill 2018 / 质控——基础设施状态",
  },
] as const;

// 七灯项工厂——给定各线 status 生成 SevenLineStatus items
export function buildSevenLineItems(
  statuses: Record<LineKey | "risk" | "data", LineStatus>,
  details: Partial<Record<LineKey | "risk" | "data", string>>,
) {
  return [
    ...LINES.map((line) => ({
      key: line.key,
      label: line.label,
      status: statuses[line.key] ?? "idle",
      detail: details[line.key],
      link: line.path,
    })),
    {
      key: "risk",
      label: "风控",
      status: statuses.risk ?? "idle",
      detail: details.risk,
    },
    {
      key: "data",
      label: "数据",
      status: statuses.data ?? "idle",
      detail: details.data,
      link: "/data",
    },
  ];
}
