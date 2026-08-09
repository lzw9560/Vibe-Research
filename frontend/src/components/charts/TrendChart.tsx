// S041 趋势看板折线图：daily_backtest_run 每日落库快照的时间序列。
// 复用 useECharts hook（S024-B 抽公共）：init+setOption+resize+dispose 统一管理。
// 三个图：hit_rate（lite）/ avg_return（lite）/ 8 战法 win_rate（strategy）。
// 空数据显示占位文案。x 轴 snapshot_date，y 轴百分比。
import { useRef } from "react";
import { useECharts } from "@/hooks/useECharts";
import type {
  BacktestSnapshotRow,
  StrategyBacktestItem,
} from "@/lib/api";

// ---- 通用样式常量 ----
const GRID = { left: 56, right: 20, top: 32, bottom: 48 };
// lite 引擎两条线复用项目主色（暖橙，对齐 winrate TrendsChart），保持视觉同源。
const PRIMARY = "#fb923c";
const PRIMARY_AREA = "rgba(251,146,60,0.12)";

// 8 战法固定色板——按 strategy_code 锁色（同战法跨日期色稳定）。
// 色相均匀分布在色轮上，饱和度/明度统一以保看板协调；8 色足够区分。
// 用 code 而非 name 作 key：name 后端可调，code 稳定（limitup_strategy.STRATEGY_REGISTRY）。
const STRATEGY_PALETTE: Record<string, string> = {
  first_plate: "#ef4444",        // 红
  consecutive_relay: "#f97316",  // 橙
  break_reseal: "#eab308",       // 黄
  low_absorption: "#22c55e",     // 绿
  reverse_package: "#14b8a6",    // 青
  n_shape_counterattack: "#3b82f6", // 蓝
  platform_breakout: "#a855f7",  // 紫
  end_of_day_sneak: "#ec4899",  // 粉
};
// 兜底色：未知战法 / palette 溢出（>8 个战法）。
const STRATEGY_FALLBACK = "#64748b"; // slate-500

/**
 * 从 strategy 行中提取所有日期 + 所有战法码（保序）。
 * - 日期按 snapshot_date 升序（趋势线左→右）。
 * - 战法序取第一个含全部战法的快照（STRATEGY_REGISTRY 顺序由后端保）。
 */
function extractStrategySeries(rows: BacktestSnapshotRow[]): {
  dates: string[];
  strategyCodes: string[];
  strategyNames: Record<string, string>;
  // values[code] = 每日 win_rate 百分比（缺日 null，断线）
  values: Record<string, (number | null)[]>;
} {
  // 仅取 strategy 行（lite 行无 strategy_breakdown_json）
  const sRows = rows.filter((r) => r.engine === "strategy");
  const dates = sRows.map((r) => r.snapshot_date);

  // 解析每日 breakdown，按 code 聚合
  const codeSet: string[] = [];
  const codeSetSeen = new Set<string>();
  const names: Record<string, string> = {};
  const perDay: Record<string, Record<string, number | null>> = {};
  for (const r of sRows) {
    let items: StrategyBacktestItem[] = [];
    if (r.strategy_breakdown_json) {
      try {
        const parsed = JSON.parse(r.strategy_breakdown_json);
        if (Array.isArray(parsed)) items = parsed as StrategyBacktestItem[];
      } catch {
        // JSON 损坏：该日所有战法断点（null），不阻断整图
      }
    }
    perDay[r.snapshot_date] = {};
    for (const it of items) {
      if (!codeSetSeen.has(it.strategy_code)) {
        codeSetSeen.add(it.strategy_code);
        codeSet.push(it.strategy_code);
        names[it.strategy_code] = it.strategy_name;
      }
      perDay[r.snapshot_date][it.strategy_code] =
        typeof it.win_rate === "number" ? it.win_rate * 100 : null;
    }
  }

  const values: Record<string, (number | null)[]> = {};
  for (const code of codeSet) {
    values[code] = dates.map((d) => perDay[d]?.[code] ?? null);
  }

  return { dates, strategyCodes: codeSet, strategyNames: names, values };
}

interface HitRateChartProps {
  rows: BacktestSnapshotRow[];
  height?: number;
}

/**
 * hit_rate 趋势（lite 引擎）：一条线，y 轴百分比。
 */
export function HitRateChart({ rows, height = 320 }: HitRateChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const liteRows = rows.filter((r) => r.engine === "lite");
  // 升序——后端 trend 端点已按日期升序返，此处保底再排一次防乱序
  const sorted = [...liteRows].sort((a, b) =>
    a.snapshot_date.localeCompare(b.snapshot_date),
  );
  const data = sorted.map((r) =>
    typeof r.hit_rate === "number" ? r.hit_rate * 100 : null,
  );

  useECharts(
    chartRef,
    () => ({
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const ps = params as Array<{ axisValue: string; data: number | null }>;
          if (!Array.isArray(ps) || ps.length === 0) return "";
          const p = ps[0];
          const v = p.data;
          return `${p.axisValue}<br/>命中率：${
            v === null ? "—" : `${v.toFixed(1)}%`
          }`;
        },
      },
      grid: GRID,
      xAxis: {
        type: "category",
        data: sorted.map((r) => r.snapshot_date),
        axisLabel: { rotate: 30 },
      },
      yAxis: {
        type: "value",
        name: "命中率(%)",
        nameGap: 32,
        axisLabel: { formatter: (v: number | string) => `${Number(v).toFixed(0)}%` },
      },
      series: [
        {
          name: "命中率",
          type: "line",
          smooth: true,
          connectNulls: true,
          data,
          itemStyle: { color: PRIMARY },
          lineStyle: { color: PRIMARY, width: 2 },
          areaStyle: { color: PRIMARY_AREA },
        },
      ],
    }),
    [rows],
    { skip: sorted.length === 0 },
  );

  if (sorted.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted-foreground/60"
        style={{ height }}
      >
        暂无命中率快照数据
      </div>
    );
  }
  return <div ref={chartRef} className="w-full" style={{ height }} />;
}

interface AvgReturnChartProps {
  rows: BacktestSnapshotRow[];
  height?: number;
}

/**
 * avg_return 趋势（lite 引擎）：一条线，y 轴百分比。
 * 后端 avg_return 为小数（0.0234 表示 2.34%），需 ×100 转 y 轴口径。
 */
export function AvgReturnChart({ rows, height = 320 }: AvgReturnChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const liteRows = rows.filter((r) => r.engine === "lite");
  const sorted = [...liteRows].sort((a, b) =>
    a.snapshot_date.localeCompare(b.snapshot_date),
  );
  const data = sorted.map((r) =>
    typeof r.avg_return === "number" ? r.avg_return * 100 : null,
  );

  useECharts(
    chartRef,
    () => ({
      tooltip: {
        trigger: "axis",
        formatter: (params: unknown) => {
          const ps = params as Array<{ axisValue: string; data: number | null }>;
          if (!Array.isArray(ps) || ps.length === 0) return "";
          const p = ps[0];
          const v = p.data;
          return `${p.axisValue}<br/>平均收益：${
            v === null ? "—" : `${v.toFixed(2)}%`
          }`;
        },
      },
      grid: GRID,
      xAxis: {
        type: "category",
        data: sorted.map((r) => r.snapshot_date),
        axisLabel: { rotate: 30 },
      },
      yAxis: {
        type: "value",
        name: "平均收益(%)",
        nameGap: 32,
        axisLabel: { formatter: (v: number | string) => `${Number(v).toFixed(1)}%` },
      },
      series: [
        {
          name: "平均收益",
          type: "line",
          smooth: true,
          connectNulls: true,
          data,
          itemStyle: { color: PRIMARY },
          lineStyle: { color: PRIMARY, width: 2 },
          areaStyle: { color: PRIMARY_AREA },
        },
      ],
    }),
    [rows],
    { skip: sorted.length === 0 },
  );

  if (sorted.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted-foreground/60"
        style={{ height }}
      >
        暂无平均收益快照数据
      </div>
    );
  }
  return <div ref={chartRef} className="w-full" style={{ height }} />;
}

interface StrategyWinRateChartProps {
  rows: BacktestSnapshotRow[];
  height?: number;
}

/**
 * 8 战法 win_rate 趋势（strategy 引擎）：每个战法一条线。
 * 解析每日 strategy_breakdown_json → 每战法一条线，最多 8 条。
 */
export function StrategyWinRateChart({ rows, height = 360 }: StrategyWinRateChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const { dates, strategyCodes, strategyNames, values } =
    extractStrategySeries(rows);

  useECharts(
    chartRef,
    () => ({
      tooltip: {
        trigger: "axis",
        // axis 模式默认列出所有非空 series；ECharts 已渲染战法名+值，不重写 formatter
        // 以保 8 线场景下 tooltip 自动对齐 + null 断线显示「-」。
      },
      legend: {
        // 战法名图例——放顶部，避免 8 条线挤占图区；类型 scroll 防 >8 溢出。
        type: "scroll",
        top: 0,
        data: strategyCodes.map((c) => strategyNames[c] ?? c),
      },
      grid: { ...GRID, top: 48 },
      xAxis: {
        type: "category",
        data: dates,
        axisLabel: { rotate: 30 },
      },
      yAxis: {
        type: "value",
        name: "胜率(%)",
        nameGap: 32,
        axisLabel: { formatter: (v: number | string) => `${Number(v).toFixed(0)}%` },
      },
      series: strategyCodes.map((code) => {
        const color = STRATEGY_PALETTE[code] ?? STRATEGY_FALLBACK;
        return {
          name: strategyNames[code] ?? code,
          type: "line",
          smooth: true,
          connectNulls: false, // 缺日断线——如实呈现战法该日无数据
          data: values[code],
          itemStyle: { color },
          lineStyle: { color, width: 2 },
        };
      }),
    }),
    [rows],
    { skip: dates.length === 0 || strategyCodes.length === 0 },
  );

  if (dates.length === 0 || strategyCodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted-foreground/60"
        style={{ height }}
      >
        暂无战法胜率快照数据
      </div>
    );
  }
  return <div ref={chartRef} className="w-full" style={{ height }} />;
}
