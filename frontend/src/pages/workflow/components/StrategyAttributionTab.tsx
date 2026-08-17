// S075 074：战法归因深看 tab——候选 × 多战法 match_strategies 结果。
// 同股多战法不排除（标注"同股多战法命中"）。
// §44 未 validated 仅复盘参考：顶部标注。
//
// 数据来源：后端 match_strategies（Phase 4b 前向测试后接入）。
// 当前为骨架占位——候选已有 9 维度评分（首板过滤产出），战法匹配结果待后端 Phase 4 接入。
// 前端先渲染候选评分明细（CandidateScoreTable）+ 战法命中占位表，后端接入后填 match 结果。
import { Badge } from "@/components/ui/Badge";
import {
  CandidateScoreTable, StrategyMatchBadge,
} from "./FirstBoardPipeline";
import type { FirstBoardCandidate, FirstBoardCandidatesResponse } from "@/lib/api";

// 8 战法清单（与后端 strategy_funnel_registry 对齐——同 HonestyBanner §44 8 战法）
const STRATEGIES = [
  { code: "breakout", name: "突破" },
  { code: "rebound", name: "反包" },
  { code: "low吸", name: "低吸" },
  { code: "board_relay", name: "接力" },
  { code: "storm_reversal", name: "暴风雨反转" },
  { code: "n_pattern", name: "N字反击" },
  { code: "first_board", name: "首板" },
  { code: "continuous_board", name: "连板" },
] as const;

interface Props {
  data: FirstBoardCandidatesResponse | null;
}

export function StrategyAttributionTab({ data }: Props) {
  const candidates: FirstBoardCandidate[] = data?.candidates ?? [];

  return (
    <div className="space-y-4">
      {/* §44 诚实标注 */}
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
        <div className="font-semibold text-amber-200">⚠ §44 未 validated 仅复盘参考</div>
        <ul className="mt-1 space-y-0.5 text-xs text-amber-100/80">
          <li>· 战法归因结果基于 9 维度评分（权重待回测校准，未 §44 validated）</li>
          <li>· 同股多战法命中不排除——同一只股可能被多个战法标记，属正常</li>
          <li>· match_strategies 完整结果待 Phase 4b 前向测试后接入</li>
        </ul>
      </div>

      {/* 候选 9 维度评分表 */}
      <div>
        <h3 className="mb-2 text-sm font-semibold">候选评分明细（9 维度）</h3>
        <CandidateScoreTable candidates={candidates} />
      </div>

      {/* 战法 × 候选 命中矩阵（占位——后端 Phase 4 接入后填 match_strategies） */}
      <div>
        <h3 className="mb-2 text-sm font-semibold">战法 × 候选 命中矩阵</h3>
        <div className="overflow-x-auto rounded-lg border border-border/40">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border/40 bg-muted/20 text-muted-foreground">
                <th className="px-2 py-2 text-left font-medium">候选</th>
                {STRATEGIES.map((s) => (
                  <th key={s.code} className="px-2 py-2 text-center font-medium">{s.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {candidates.length === 0 ? (
                <tr>
                  <td
                    colSpan={STRATEGIES.length + 1}
                    className="px-2 py-6 text-center text-muted-foreground/60"
                  >
                    候选池为空
                  </td>
                </tr>
              ) : (
                candidates.slice(0, 20).map((c) => {
                  // 占位：当前用评分 total>60 标记首板战法命中（其他战法待 Phase 4 接入）
                  const firstBoardMatched = c.total >= 60;
                  return (
                    <tr
                      key={c.code}
                      className="border-b border-border/20 hover:bg-muted/10"
                    >
                      <td className="px-2 py-1.5">
                        <span className="text-muted-foreground">#{c.rank}</span>{" "}
                        <span className="font-mono">{c.code}</span>{" "}
                        <span className="text-foreground">{c.name}</span>
                        <div className="text-[10px] text-muted-foreground/60">
                          total {c.total.toFixed(1)}
                        </div>
                      </td>
                      {STRATEGIES.map((s) => {
                        // 占位：仅首板战法有真实命中判定，其余待 Phase 4
                        const matched = s.code === "first_board" ? firstBoardMatched : false;
                        const isPlaceholder = s.code !== "first_board";
                        return (
                          <td key={s.code} className="px-2 py-1.5 text-center">
                            {isPlaceholder ? (
                              <span className="text-[10px] text-muted-foreground/40">待 P4</span>
                            ) : (
                              <StrategyMatchBadge strategy={s.name} matched={matched} />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        {candidates.length > 20 && (
          <p className="mt-1 text-[11px] text-muted-foreground/60">
            仅显示前 20 只候选（共 {candidates.length} 只）· 完整列表见上表
          </p>
        )}
      </div>

      {/* 同股多战法命中提示 */}
      <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <Badge variant="info">提示</Badge>
          <span>同股多战法命中不排除</span>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground/70">
          一只股可能同时满足多个战法触发条件（如"首板"+"突破"双命中），
          系统不主动去重——由用户自行选择主战法。
        </p>
      </div>
    </div>
  );
}
