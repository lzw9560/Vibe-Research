// S025-B3 胜率拆分区：DataTable 按 sector / 按 strategy 下钻。
// sector/strategy 任一非空即下钻对应维度；两者都空 → 占位。
// 后端 /winrate/sector/{sector}、/winrate/strategy/{strategy} 返回单对象统计；
// 包裹 [data] 作单行表，列随维度切换（板块/战法 名 + 总交易/胜数/胜率/平均收益）。
import { useWinRateSector, useWinRateStrategy } from "@/lib/query";
import { DataTable } from "@/components/ui/DataTable";
import type { Column } from "@/components/ui/DataTable";
import { SkeletonTable } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";

interface BreakdownTableProps {
  sector?: string;
  strategy?: string;
  windowSize: number;
}

interface SectorStats {
  sector: string;
  total_trades: number;
  win_count: number;
  win_rate: number;
  avg_return: number;
}

interface StrategyStats {
  strategy: string;
  total_trades: number;
  win_count: number;
  win_rate: number;
  avg_return: number;
}

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const pct2 = (v: number) => `${v.toFixed(2)}%`;

const sectorColumns: Column<SectorStats>[] = [
  { key: "sector", header: "板块" },
  { key: "total_trades", header: "总交易", align: "right" },
  { key: "win_count", header: "胜数", align: "right" },
  { key: "win_rate", header: "胜率", align: "right", render: (r) => pct(r.win_rate) },
  { key: "avg_return", header: "平均收益", align: "right", render: (r) => pct2(r.avg_return) },
];

const strategyColumns: Column<StrategyStats>[] = [
  { key: "strategy", header: "战法" },
  { key: "total_trades", header: "总交易", align: "right" },
  { key: "win_count", header: "胜数", align: "right" },
  { key: "win_rate", header: "胜率", align: "right", render: (r) => pct(r.win_rate) },
  { key: "avg_return", header: "平均收益", align: "right", render: (r) => pct2(r.avg_return) },
];

export function BreakdownTable({ sector, strategy, windowSize }: BreakdownTableProps) {
  // 两个 hook 均调用（rules of hooks），enabled 由 hook 内部按值非空控制；
  // 仅读活跃维度（sector 优先）的 data。
  const sectorQ = useWinRateSector(sector ?? "", windowSize);
  const strategyQ = useWinRateStrategy(strategy ?? "", windowSize);

  if (!sector && !strategy) {
    return <EmptyState title="选择板块或战法" description="选定一个维度以查看下钻统计" />;
  }

  if (sector) {
    const { data, isLoading, isError } = sectorQ;
    if (isLoading) return <SkeletonTable />;
    if (isError || !data) {
      return <EmptyState title="暂无该板块统计" description="该板块在窗口内无记录" />;
    }
    return (
      <DataTable
        data={[data]}
        columns={sectorColumns}
        keyExtractor={(r) => r.sector}
      />
    );
  }

  // strategy 分支
  const { data, isLoading, isError } = strategyQ;
  if (isLoading) return <SkeletonTable />;
  if (isError || !data) {
    return <EmptyState title="暂无该战法统计" description="该战法在窗口内无记录" />;
  }
  return (
    <DataTable
      data={[data]}
      columns={strategyColumns}
      keyExtractor={(r) => r.strategy}
    />
  );
}
