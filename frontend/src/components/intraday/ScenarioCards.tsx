// S063 T23：Layer 3 条件场景推演——两栏并列 if-then 卡片。
// 历史参照标注样本量（CC1：不编准确率）。14:30 前不显示（T+1 预判时段）。
import { useIntradayScenarios } from "@/lib/query";
import { Skeleton } from "@/components/ui/Skeleton";

export function ScenarioCards() {
  const { data, isLoading } = useIntradayScenarios();

  if (isLoading) {
    return <Skeleton className="h-[180px] w-full" />;
  }

  if (!data || data.scenarios.length === 0) {
    return (
      <div className="rounded-lg bg-muted/10 p-4 text-sm text-muted-foreground">
        {data ? "当前无有效采样数据，无法推演" : "场景推演未取得"}
      </div>
    );
  }

  const { scenarios, history_reference: hist } = data;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        {scenarios.map((s, i) => (
          <div
            key={i}
            className="rounded-lg border border-border/40 bg-muted/5 p-3"
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                IF
              </span>
              <p className="text-sm font-medium">{s.condition}</p>
            </div>
            <div className="space-y-1 text-xs text-muted-foreground">
              <p>
                <span className="font-semibold text-foreground/80">THEN</span> {s.impact}
              </p>
              <p>
                <span className="font-semibold text-foreground/80">建议</span> {s.suggestion}
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* 历史参照——诚实标注样本量（CC1） */}
      <div className="rounded border border-border/30 bg-muted/5 p-3 text-xs text-muted-foreground">
        <p className="font-medium text-foreground/70">历史参照</p>
        <p className="mt-1">{hist.note}</p>
        {hist.sample_size > 0 && (
          <div className="mt-1 flex gap-3">
            <span>后续上行 {hist.follow_up_distribution.up}</span>
            <span>持平 {hist.follow_up_distribution.flat}</span>
            <span>下行 {hist.follow_up_distribution.down}</span>
            <span className="text-muted-foreground/60">（样本 {hist.sample_size}）</span>
          </div>
        )}
      </div>
    </div>
  );
}
