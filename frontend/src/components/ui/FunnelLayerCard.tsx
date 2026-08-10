import { useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { FunnelLayer, PassedItem } from "@/lib/candidates";
import { useWorkflowStates } from "@/lib/query";
import { STATUS_COLORS } from "@/components/workflow/statusMeta";

// S031 R16/R17：漏斗层公共卡片——conditions + passed + filtered_out + 输入→输出计数。
// 候选池页（FunnelLayers，neutral）与盘前简报因子层（FactorSection，info）共用。
// 候选池的 rerun/downstream 经 footer 槽注入；因子层不用 footer。
// S033 T7/T12：passed 行带 workflow_state 状态色块、filtered_out 行带红淡徽标。
// S045：passed 每行显示得分（gene_score/confidence_value/suggested_pct 按层语义）+
//   默认按得分降序（可切回原序）+ 多选筛选（有战法按战法、R3 按触发类型，"或"逻辑）。

/** 排序用数值分：gene_score（0-100）优先，其次 confidence_value / suggested_pct（0-1）。缺分 null。 */
function scoreValue(c: PassedItem): number | null {
  if (typeof c.gene_score === "number") return c.gene_score;
  if (typeof c.confidence_value === "number") return c.confidence_value;
  if (typeof c.suggested_pct === "number") return c.suggested_pct;
  return null;
}

/** 展示用得分文案：基因分原值（0-100），置信度/仓位转百分比。 */
function scoreDisplay(c: PassedItem): string | null {
  if (typeof c.gene_score === "number") return c.gene_score.toFixed(1);
  if (typeof c.confidence_value === "number") return `${(c.confidence_value * 100).toFixed(0)}%`;
  if (typeof c.suggested_pct === "number") return `${(c.suggested_pct * 100).toFixed(0)}%`;
  return null;
}

interface Props {
  layer: FunnelLayer;
  onPick?: (code: string) => void;
  /** conditions chips 色调：因子层 info（权重公式）/ 候选池 neutral（过滤规则） */
  variant?: "info" | "neutral";
  /** 底部操作槽（候选池 rerun/downstream 注入） */
  footer?: ReactNode;
  /** 交易日：传了则叠加 workflow_state 状态徽标（S033） */
  date?: string;
  className?: string;
}

export function FunnelLayerCard({ layer, onPick, variant = "neutral", footer, date, className }: Props) {
  const missing = layer.data_status === "未取得";
  // S033 决策 ⑥：一次取全日状态再前端 Map filter（React hooks 不得在 map callback 调）。
  // date 缺省（如单测/无日期上下文）时 enabled=false，不发请求。
  const { data: stateList } = useWorkflowStates(date ?? undefined, { enabled: !!date });
  const stateMap = useMemo(
    () => new Map((stateList?.states ?? []).map((s) => [s.code, s.status])),
    [stateList],
  );

  // S045：得分排序（默认降序）+ 多选筛选
  const [sortByScore, setSortByScore] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const passed = layer.passed ?? [];

  // 筛选维度：优先战法（best_strategy/matched_strategy），否则 R3 触发类型 matched_triggers
  const filterOptions = useMemo(() => {
    const strategies = Array.from(
      new Set(passed.map((c) => c.best_strategy ?? c.matched_strategy).filter((s): s is string => !!s)),
    );
    if (strategies.length > 0) return { kind: "strategy" as const, values: strategies };
    const triggers = Array.from(new Set(passed.flatMap((c) => c.matched_triggers ?? [])));
    if (triggers.length > 0) return { kind: "trigger" as const, values: triggers };
    return null;
  }, [passed]);

  // rerun 后旧选中值可能失效 → 只保留仍在选项里的（避免误清空全部）
  const activeSelected = useMemo(() => {
    if (!filterOptions || selected.size === 0) return new Set<string>();
    return new Set([...selected].filter((v) => filterOptions.values.includes(v)));
  }, [filterOptions, selected]);

  const visible = useMemo(() => {
    let list = passed;
    if (filterOptions && activeSelected.size > 0) {
      list = list.filter((c) =>
        filterOptions.kind === "strategy"
          ? !!((c.best_strategy ?? c.matched_strategy) && activeSelected.has((c.best_strategy ?? c.matched_strategy) as string))
          : (c.matched_triggers ?? []).some((t) => activeSelected.has(t)),
      );
    }
    if (sortByScore) {
      list = [...list].sort(
        (a, b) => (scoreValue(b) ?? Number.NEGATIVE_INFINITY) - (scoreValue(a) ?? Number.NEGATIVE_INFINITY),
      );
    }
    return list;
  }, [passed, filterOptions, activeSelected, sortByScore]);

  const toggleFilter = (v: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v);
      else next.add(v);
      return next;
    });

  return (
    <div className={cn("rounded-lg border border-border/40 bg-card/30 p-3 max-w-2xl", className)}>
      <div className="flex items-center justify-between">
        <div className="font-medium">
          <span className="mr-2 text-xs text-muted-foreground">{layer.layer_id}</span>
          {layer.name}
        </div>
        <div className="text-xs text-muted-foreground">
          输入 <span className="text-foreground">{layer.input_count}</span> → 输出{" "}
          <span className="text-foreground">{layer.output_count}</span>
        </div>
      </div>

      {missing && layer.data_reason && (
        <div className="mt-2 text-sm text-warning">该层数据未取得：{layer.data_reason}</div>
      )}

      {layer.conditions && layer.conditions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {layer.conditions.map((c, i) => (
            <span
              key={i}
              className={cn(
                "rounded px-2 py-0.5 text-xs",
                variant === "info" ? "bg-primary/10 text-primary" : "bg-muted/40",
              )}
              title={c}
            >
              {c.length > 24 ? `${c.slice(0, 24)}…` : c}
            </span>
          ))}
        </div>
      )}

      {!missing && passed.length > 0 && (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              通过候选（{activeSelected.size > 0 ? `${visible.length}/${passed.length}` : passed.length}）
            </span>
            <button
              type="button"
              onClick={() => setSortByScore((v) => !v)}
              className="text-xs text-primary hover:underline"
            >
              {sortByScore ? "得分排序 ↓" : "恢复原序"}
            </button>
          </div>

          {/* S045 多选筛选：战法 / R3 触发类型 */}
          {filterOptions && filterOptions.values.length > 0 && (
            <div className="mb-1 flex flex-wrap gap-1">
              {filterOptions.values.map((v) => {
                const on = activeSelected.size === 0 || activeSelected.has(v);
                return (
                  <button
                    key={v}
                    type="button"
                    onClick={() => toggleFilter(v)}
                    className={cn(
                      "rounded px-2 py-0.5 text-xs transition-colors",
                      activeSelected.has(v)
                        ? "bg-primary text-primary-foreground"
                        : on
                          ? "bg-muted/40 text-foreground hover:bg-muted/60"
                          : "bg-muted/20 text-muted-foreground",
                    )}
                  >
                    {v}
                  </button>
                );
              })}
            </div>
          )}

          <div className="space-y-0.5">
            {visible.slice(0, 15).map((c) => {
              const disp = scoreDisplay(c);
              return (
                <button
                  key={c.code}
                  type="button"
                  onClick={() => onPick?.(c.code)}
                  className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-muted/50"
                  title={c.name}
                >
                  {date && (
                    <span
                      aria-hidden
                      className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        STATUS_COLORS[stateMap.get(c.code) ?? ""] ?? "bg-gray-200",
                      )}
                    />
                  )}
                  <span className="flex-1 truncate">
                    {c.name} <span className="text-xs text-muted-foreground">{c.code}</span>
                  </span>
                  {disp !== null && (
                    <span className="text-xs font-medium text-primary">{disp}</span>
                  )}
                </button>
              );
            })}
            {visible.length > 15 && (
              <div className="text-xs text-muted-foreground">…共 {visible.length} 条</div>
            )}
            {visible.length === 0 && (
              <div className="text-xs text-muted-foreground">当前筛选无匹配候选</div>
            )}
          </div>
        </div>
      )}

      {layer.filtered_out && layer.filtered_out.length > 0 && (
        <div className="mt-2 grid gap-1 text-xs">
          <div className="text-muted-foreground">被过滤（{layer.filtered_out.length}）：</div>
          {layer.filtered_out.slice(0, 10).map((f) => (
            <div key={f.code} className="flex items-center gap-2">
              {/* S033 T12/R8：filtered 红淡徽标（与 workflow_state 的 filtered 一致） */}
              <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-red-300" />
              <span className="flex flex-1 justify-between gap-2">
                <span className="truncate" title={`${f.name ?? ""} ${f.code}`}>
                  {f.name ? `${f.name} ${f.code}` : f.code}
                </span>
                <span className="truncate text-muted-foreground" title={f.reason}>{f.reason}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {footer && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border/40 pt-2">
          {footer}
        </div>
      )}
    </div>
  );
}
