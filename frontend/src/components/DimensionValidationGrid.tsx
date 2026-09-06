// S165 wire: 维度验证卡网格容器——fetch GET /api/evaluation/dims，渲染 12 维 DimensionValidationCard。
// 后端未就绪/空 → mock fixture fallback + "mock" 徽标（honest transition，不 break UI）。
// DimensionValidationCard 保持纯展示组件（不变），此容器负责数据获取 + 降级 + 网格布局。
import { DimensionValidationCard } from "@/components/DimensionValidationCard";
import { useEvaluationDims } from "@/lib/query";
import { dimensionValidationMocks } from "@/lib/__fixtures__/dimension-validation.mock";
import type { DimensionValidationRecord } from "@/lib/verifier-contract";

export function DimensionValidationGrid() {
  const { data, isLoading, error } = useEvaluationDims();

  // honest fallback: 后端未就绪/空 → mock fixture + "mock" 徽标。
  const hasReal = !!data && data.length > 0;
  const records: readonly DimensionValidationRecord[] = hasReal
    ? data!
    : dimensionValidationMocks;
  const isMock = !hasReal;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">§44 维度验证（12 维 verdict）</h3>
        <div className="flex items-center gap-1.5">
          {isLoading && (
            <span className="text-xs text-muted-foreground">加载中…</span>
          )}
          {error && !isLoading && (
            <span className="text-xs text-red-500">后端未就绪，显示 mock</span>
          )}
          {isMock && !isLoading && (
            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600">
              MOCK
            </span>
          )}
          {!isMock && (
            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-600">
              LIVE
            </span>
          )}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {records.map((r) => (
          <DimensionValidationCard key={r.dimension_id} record={r} />
        ))}
      </div>
    </div>
  );
}
