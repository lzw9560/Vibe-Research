// S179 Phase 1: 选股器筛选面板——6 类条件组（行业/市值/PE/PB/ROE/涨幅）+ preset 选项。
// grill #12: 统一筛选 API vs 前端 fan-out 待定——面板收集 filter state 但不触发后端查询。
// 条件 state 由 ScreenerPage 持有（controlled），面板纯展示 + emit onChange。
import { GlassCard } from "@/components/ui/GlassCard";
import { SlidersHorizontal, RotateCcw } from "lucide-react";
import { SCREENER_PRESETS } from "./presets";

/** 筛选条件 state——所有字段 controlled by ScreenerPage */
export interface ScreenerFilters {
  industry: string;
  marketCapMin: number | null;
  marketCapMax: number | null;
  peMin: number | null;
  peMax: number | null;
  pbMin: number | null;
  pbMax: number | null;
  roeMin: number | null;
  roeMax: number | null;
  changeMin: number | null;
  changeMax: number | null;
}

export const DEFAULT_FILTERS: ScreenerFilters = {
  industry: "",
  marketCapMin: null,
  marketCapMax: null,
  peMin: null,
  peMax: null,
  pbMin: null,
  pbMax: null,
  roeMin: null,
  roeMax: null,
  changeMin: null,
  changeMax: null,
};

/** 数值型 filter key（排除 industry string 字段，用于泛型条件组渲染） */
type NumericKey = Exclude<keyof ScreenerFilters, "industry">;

interface FilterPanelProps {
  filters: ScreenerFilters;
  onChange: (filters: ScreenerFilters) => void;
  onReset: () => void;
  onPresetSelect: (path: string) => void;
}

interface ConditionGroup {
  label: string;
  minKey: NumericKey;
  maxKey: NumericKey;
  unit: string;
}

const CONDITION_GROUPS: readonly ConditionGroup[] = [
  { label: "市值", minKey: "marketCapMin", maxKey: "marketCapMax", unit: "亿" },
  { label: "PE", minKey: "peMin", maxKey: "peMax", unit: "" },
  { label: "PB", minKey: "pbMin", maxKey: "pbMax", unit: "" },
  { label: "ROE", minKey: "roeMin", maxKey: "roeMax", unit: "%" },
  { label: "涨幅", minKey: "changeMin", maxKey: "changeMax", unit: "%" },
];

/** 字符串 → number | null（空串→null，非法→null 不更新由调用方跳过） */
function toNumOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const num = Number(trimmed);
  return Number.isNaN(num) ? null : num;
}

/** 不可变更新单个数值 filter 字段。
 *  computed property spread 需 assertion——安全因为所有 NumericKey 值类型均为 number | null。 */
function updateNumeric(
  filters: ScreenerFilters,
  key: NumericKey,
  value: string,
): ScreenerFilters {
  return { ...filters, [key]: toNumOrNull(value) } as ScreenerFilters;
}

export function FilterPanel({
  filters,
  onChange,
  onReset,
  onPresetSelect,
}: FilterPanelProps) {
  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          <SlidersHorizontal className="h-4 w-4" />
          筛选条件
        </div>
        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
        >
          <RotateCcw className="h-3 w-3" />
          重置
        </button>
      </div>

      {/* 行业（文本输入） */}
      <div className="mb-3">
        <label className="mb-1 block text-[12px] text-muted-foreground">行业</label>
        <input
          type="text"
          value={filters.industry}
          onChange={(e) => onChange({ ...filters, industry: e.target.value })}
          placeholder="输入行业名称（如：银行、半导体）"
          className="w-full rounded border border-border bg-background px-2 py-1 text-sm outline-none focus:border-primary/50"
        />
      </div>

      {/* 数值范围条件组（min—max） */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        {CONDITION_GROUPS.map((g) => (
          <div key={g.label}>
            <label className="mb-1 block text-[12px] text-muted-foreground">
              {g.label}
              {g.unit && ` (${g.unit})`}
            </label>
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={filters[g.minKey] ?? ""}
                onChange={(e) => onChange(updateNumeric(filters, g.minKey, e.target.value))}
                placeholder="最小"
                className="w-full rounded border border-border bg-background px-2 py-1 text-sm outline-none focus:border-primary/50"
              />
              <span className="shrink-0 text-muted-foreground">—</span>
              <input
                type="number"
                value={filters[g.maxKey] ?? ""}
                onChange={(e) => onChange(updateNumeric(filters, g.maxKey, e.target.value))}
                placeholder="最大"
                className="w-full rounded border border-border bg-background px-2 py-1 text-sm outline-none focus:border-primary/50"
              />
            </div>
          </div>
        ))}
      </div>

      {/* preset 选项（跳现有 /limitup/* 路由，grill #5 非重建） */}
      <div className="mt-4 border-t border-border/40 pt-3">
        <label className="mb-1 block text-[12px] text-muted-foreground">
          打板 preset（跳现有子页）
        </label>
        <select
          defaultValue=""
          onChange={(e) => {
            const path = e.target.value;
            if (path) onPresetSelect(path);
          }}
          className="w-full rounded border border-border bg-background px-2 py-1 text-sm outline-none focus:border-primary/50"
        >
          <option value="" disabled>
            选择 preset 跳转…
          </option>
          {SCREENER_PRESETS.map((p) => (
            <option key={p.id} value={p.path}>
              {p.name} — {p.description}
            </option>
          ))}
        </select>
      </div>
    </GlassCard>
  );
}
