// S075 068-073：首板流 Pipeline 主视图——5 步闭环可视化。
// 参考 SelectionPipeline 的 PipelineNode / ArrowDown 样式，自定义首板流逻辑。
// §44 诚实标注：9 维度评分未 validated 仅参考；阈值/权重待回测校准。
//
// 节点颜色语义（与现有体系对齐）：
//   绿 = 通过/已运行  红 = 剔除  黄 = 待确认  灰 = 未运行
//   实线 = 已过滤/已运行  虚线 = 待运行/漂移
//
// 数据来源：useFirstBoardCandidates（GET /api/workflow/first-board/candidates）
// ②-⑤ 节点后端 Phase 2-4 实现，前端做骨架占位（数据未取得时显示"待 Phase X"降态）。
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { HonestyBanner } from "@/components/ui/HonestyBanner";
import type {
  FirstBoardCandidate, FirstBoardCandidatesResponse, FirstBoardExcludedItem,
} from "@/lib/api";

// ---- 节点样式（复用 SelectionPipeline 的 NODE / NODE_DASHED 语义）----
const NODE = "rounded-lg border border-border/40 bg-card/40 p-3";
const NODE_DASHED = "rounded-lg border border-dashed p-3";
const NODE_GREEN = "rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3";
const NODE_AMBER = "rounded-lg border border-amber-500/40 bg-amber-500/5 p-3";
const NODE_RED = "rounded-lg border border-destructive/40 bg-destructive/5 p-3";

// ---- 箭头（复用 SelectionPipeline 的 ArrowDown）----
function ArrowDown({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center py-0.5">
      <div className="h-2 w-px bg-border/40" />
      <span className="text-[9px] text-border/50 leading-none">▼</span>
      {label && <span className="text-[10px] text-muted-foreground">{label}</span>}
    </div>
  );
}

// ---- 收缩条（input→output 可视化）----
function FunnelShrinkBar({ input, output }: { input: number; output: number }) {
  const ratio = input > 0 ? Math.max(output / input, 0.12) : 0.12;
  return (
    <div className="flex items-center gap-1.5 px-1">
      <div className="h-1.5 flex-1 rounded bg-muted/30" />
      <div className="h-1.5 rounded bg-primary/40" style={{ width: `${ratio * 100}%` }} />
      <span className="text-[10px] text-muted-foreground">{input}→{output}</span>
    </div>
  );
}

// ---- ① 筛选节点：涨停股池 → 首板过滤 → 3层剔除 ----
function FilterPipelineNode({ data }: { data: FirstBoardCandidatesResponse | null }) {
  const [expanded, setExpanded] = useState(false);

  const ztPoolCount = data?.zt_pool_count ?? "—";
  const firstBoardCount = data?.first_board_count ?? "—";
  const excluded = data?.excluded ?? [];
  const candidates = data?.candidates ?? [];

  // 三层剔除分组
  const excludedByLayer: Record<number, FirstBoardExcludedItem[]> = { 1: [], 2: [], 3: [] };
  for (const e of excluded) {
    const layer = (e.layer as number) ?? 1;
    if (!excludedByLayer[layer]) excludedByLayer[layer] = [];
    excludedByLayer[layer].push(e);
  }

  const layerNames: Record<number, string> = {
    1: "层1 · 封板质量",
    2: "层2 · 筹码结构",
    3: "层3 · 市场环境",
  };
  const layerReasons: Record<number, string> = {
    1: "炸板≥2 / 首封≥14:00 / 封单<流通市值×0.5%",
    2: "换手>25% / 成交额>15亿 / 量比≥2.0",
    3: "同板块涨停<2 且无题材（孤板）",
  };

  return (
    <div className="space-y-1">
      {/* 涨停股池 */}
      <div className={NODE_GREEN}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">涨停股池</div>
            <div className="text-[11px] text-muted-foreground">em_zt_topic_pool · T日涨停 → 选 T+1</div>
          </div>
          <div className="text-lg font-bold text-emerald-400">{ztPoolCount}</div>
        </div>
      </div>
      <ArrowDown label="lbc=1 首板过滤" />

      {/* 首板过滤 */}
      <div className={NODE_GREEN}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">首板过滤</div>
            <div className="text-[11px] text-muted-foreground">连板数 lbc=1（首板涨停）</div>
          </div>
          <div className="text-lg font-bold text-emerald-400">{firstBoardCount}</div>
        </div>
      </div>
      <ArrowDown label="3 层剔除" />

      {/* 三层剔除节点（可展开剔除原因） */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className={cn(NODE, "w-full text-left hover:bg-card/60")}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">L1+L2+L3</span>
            <span className="text-sm font-medium">三层剔除</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {firstBoardCount === "—" ? "—" : `${firstBoardCount}→${candidates.length}`}
            </span>
            <span className="text-[10px] text-muted-foreground">{expanded ? "▼ 收起" : "▶ 展开"}</span>
          </div>
        </div>
        <div className="mt-1 text-[11px] text-muted-foreground/80">
          共剔除 {excluded.length} 只 · 点展开看分层原因
        </div>
      </button>

      {expanded && (
        <div className="space-y-2 border-t border-border/30 pt-2">
          <FunnelShrinkBar
            input={typeof firstBoardCount === "number" ? firstBoardCount : 0}
            output={candidates.length}
          />
          {[1, 2, 3].map((layer) => (
            <div key={layer} className={cn(NODE_RED, "opacity-90")}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-destructive">{layerNames[layer]}</span>
                <span className="text-[10px] text-destructive">剔除 {excludedByLayer[layer].length} 只</span>
              </div>
              <div className="mt-0.5 text-[10px] text-muted-foreground">{layerReasons[layer]}</div>
              {excludedByLayer[layer].length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {excludedByLayer[layer].slice(0, 10).map((e) => (
                    <span
                      key={e.code}
                      title={e.reason}
                      className="rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] text-destructive"
                    >
                      {e.code} <span className="text-destructive/60">{e.reason}</span>
                    </span>
                  ))}
                  {excludedByLayer[layer].length > 10 && (
                    <span className="text-[10px] text-muted-foreground/60">
                      …共 {excludedByLayer[layer].length} 只
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <ArrowDown label="9 维度评分" />

      {/* 候选池（评分排序后） */}
      <div className={NODE}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">候选池</div>
            <div className="text-[11px] text-muted-foreground">9 维度加权评分 · 降序</div>
          </div>
          <div className="text-lg font-bold text-primary">{candidates.length}</div>
        </div>
      </div>
    </div>
  );
}

// ---- 大盘3因素灯（②确认节点用）----
function MarketEnvLamps({ data }: { data: FirstBoardCandidatesResponse | null }) {
  const env = data?.env_flags;
  const dropPct = env?.market_drop_pct ?? null;
  const highRisk = env?.high_risk ?? false;
  const maxBoards = env?.max_boards ?? null;
  const ladderBroken = env?.ladder_broken ?? false;

  // 灯色：绿=正常 / 黄=减仓 / 红=不建仓
  const dropColor = highRisk ? "red" : "yellow";
  const ladderColor = ladderBroken ? "red" : "green";
  const boardColor = maxBoards != null && maxBoards >= 2 ? "green" : "yellow";

  const Lamp = ({ color, label, value }: { color: "green" | "yellow" | "red"; label: string; value: string }) => (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "h-2.5 w-2.5 rounded-full",
          color === "green" && "bg-emerald-500",
          color === "yellow" && "bg-yellow-400",
          color === "red" && "bg-destructive",
        )}
      />
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-[11px] font-mono text-foreground">{value}</span>
    </div>
  );

  return (
    <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-3">
      <Lamp
        color={dropColor as "green" | "yellow" | "red"}
        label="大盘跌"
        value={dropPct != null ? `${dropPct.toFixed(2)}%` : "—"}
      />
      <Lamp
        color={ladderColor as "green" | "yellow" | "red"}
        label="连板梯队"
        value={ladderBroken ? "断裂" : "正常"}
      />
      <Lamp
        color={boardColor as "green" | "yellow" | "red"}
        label="最高板"
        value={maxBoards != null ? `${maxBoards} 板` : "—"}
      />
    </div>
  );
}

// ---- ② 确认节点（Phase 2 后端实现，前端占位）----
function ConfirmNode({ data }: { data: FirstBoardCandidatesResponse | null }) {
  const candidates = data?.candidates ?? [];
  const hasData = candidates.length > 0;
  return (
    <div className={hasData ? NODE_AMBER : NODE_DASHED}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-amber-300">② 确认</div>
          <div className="text-[11px] text-muted-foreground">竞价 + 开盘 10 分钟 + 大盘 3 因素</div>
        </div>
        <span className="rounded bg-amber-500/20 px-1 text-[10px] text-amber-300">
          {hasData ? "待 Phase 2" : "未运行"}
        </span>
      </div>
      {/* 大盘3因素灯 */}
      <MarketEnvLamps data={data} />
      <div className="mt-2 text-[10px] text-muted-foreground/70">
        逐只状态：待确认 → 确认中 → ✅/❌（Phase 2 竞价+开盘确认后接入）
      </div>
    </div>
  );
}

// ---- ③ 建仓节点 ----
function PositionNode({ data }: { data: FirstBoardCandidatesResponse | null }) {
  const candidates = data?.candidates ?? [];
  const top = candidates.slice(0, 5);
  return (
    <div className={top.length > 0 ? NODE : NODE_DASHED}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">③ 建仓</div>
          <div className="text-[11px] text-muted-foreground">前 3-5 只 + 评分 + 仓位</div>
        </div>
        <span className="rounded bg-primary/20 px-1 text-[10px] text-primary">
          {top.length > 0 ? `${top.length} 候选` : "待 Phase 3"}
        </span>
      </div>
      {top.length > 0 ? (
        <div className="mt-2 space-y-1">
          {top.map((c) => (
            <div key={c.code} className="flex items-center justify-between text-[11px]">
              <span className="text-foreground">
                #{c.rank} {c.code} {c.name}
              </span>
              <span className="font-mono text-primary">{c.total.toFixed(1)}</span>
            </div>
          ))}
          <div className="mt-1 text-[10px] text-muted-foreground/60">
            风控：止损 −3% / 止盈 +5% / max_hold_days=1 / T+1 必卖
          </div>
        </div>
      ) : (
        <div className="mt-2 text-[10px] text-muted-foreground/60">
          候选池为空，无建仓标的
        </div>
      )}
    </div>
  );
}

// ---- ④ 卖出节点 ----
function SellNode() {
  return (
    <div className={NODE_DASHED}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">④ 卖出</div>
          <div className="text-[11px] text-muted-foreground">T+1 持仓 + 止盈止损线</div>
        </div>
        <span className="rounded bg-muted/30 px-1 text-[10px] text-muted-foreground">待 Phase 3</span>
      </div>
      <div className="mt-1 text-[10px] text-muted-foreground/70">
        T+1 必卖 · 冲高&gt;5% 止盈 · 跌破−3% 止损 · 默认竞价开盘卖
      </div>
    </div>
  );
}

// ---- ⑤ 结算节点 ----
function SettlementNode() {
  return (
    <div className={NODE_DASHED}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">⑤ 结算</div>
          <div className="text-[11px] text-muted-foreground">盈亏归因 + 漏单 + forward_test</div>
        </div>
        <span className="rounded bg-muted/30 px-1 text-[10px] text-muted-foreground">待 Phase 4</span>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-[10px] text-muted-foreground sm:grid-cols-3">
        <span>盈亏归因</span>
        <span>漏单对账</span>
        <span>lift 四态判定</span>
      </div>
      <div className="mt-1 text-[10px] text-muted-foreground/60">
        forward_test validation_status：validated / 未 validated / 探索性 / 劣于随机
      </div>
    </div>
  );
}

// ---- ⑤ 飞书通知状态栏（075）----
function FeishuStatusBar() {
  const statuses = [
    { label: "确认变化", status: "待 Phase 2" },
    { label: "建仓提醒", status: "待 Phase 3" },
    { label: "卖出提醒", status: "待 Phase 3" },
    { label: "暴风雨预警", status: "待 Phase 2" },
  ];
  return (
    <div className={NODE}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">飞书通知状态</span>
        <span className="text-[10px] text-muted-foreground/60">全链路推送状态展示</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {statuses.map((s) => (
          <div key={s.label} className="rounded bg-muted/20 px-2 py-1.5">
            <div className="text-[10px] text-muted-foreground/70">{s.label}</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground/50">{s.status}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// 主组件
// ============================================================================

interface Props {
  data: FirstBoardCandidatesResponse | null;
  isLoading?: boolean;
}

export function FirstBoardPipeline({ data, isLoading }: Props) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className={cn(NODE, "animate-pulse")}>加载中…</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <HonestyBanner />

      {/* 数据日期 + 涨停池/首板数 概览 */}
      {data && (
        <div className={NODE}>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="text-muted-foreground/70">数据日期：{data.date}</span>
            <span className="text-muted-foreground/40">·</span>
            <span className="text-muted-foreground/70">
              涨停池 <span className="font-mono text-foreground">{data.zt_pool_count}</span>
            </span>
            <span className="text-muted-foreground/40">·</span>
            <span className="text-muted-foreground/70">
              首板 <span className="font-mono text-foreground">{data.first_board_count}</span>
            </span>
            <span className="text-muted-foreground/40">·</span>
            <span className="text-muted-foreground/70">
              候选 <span className="font-mono text-primary">{data.candidates.length}</span>
            </span>
            <span className="text-muted-foreground/40">·</span>
            <span className="text-muted-foreground/70">
              剔除 <span className="font-mono text-destructive">{data.excluded.length}</span>
            </span>
          </div>
        </div>
      )}

      {/* 5 步闭环 */}
      <FilterPipelineNode data={data} />
      <ArrowDown label="② 确认" />
      <ConfirmNode data={data} />
      <ArrowDown label="③ 建仓" />
      <PositionNode data={data} />
      <ArrowDown label="④ 卖出" />
      <SellNode />
      <ArrowDown label="⑤ 结算" />
      <SettlementNode />

      {/* 飞书通知状态栏 */}
      <div className="mt-3">
        <FeishuStatusBar />
      </div>

      {/* §44 诚实标注脚注 */}
      {data?.note && (
        <div className="mt-2 text-[11px] text-amber-200/70">{data.note}</div>
      )}
    </div>
  );
}

// 候选评分明细表（供 FirstBoardPage 战法归因 tab 复用）
export function CandidateScoreTable({ candidates }: { candidates: FirstBoardCandidate[] }) {
  if (candidates.length === 0) {
    return (
      <div className={NODE_DASHED}>
        <p className="text-xs text-muted-foreground">候选池为空</p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border/40 text-muted-foreground">
            <th className="px-2 py-1.5 text-left font-medium">#</th>
            <th className="px-2 py-1.5 text-left font-medium">代码</th>
            <th className="px-2 py-1.5 text-left font-medium">名称</th>
            <th className="px-2 py-1.5 text-right font-medium">总分</th>
            <th className="px-2 py-1.5 text-right font-medium">板块</th>
            <th className="px-2 py-1.5 text-right font-medium">游资</th>
            <th className="px-2 py-1.5 text-right font-medium">封板</th>
            <th className="px-2 py-1.5 text-right font-medium">筹码</th>
            <th className="px-2 py-1.5 text-right font-medium">竞价</th>
            <th className="px-2 py-1.5 text-right font-medium">北向</th>
            <th className="px-2 py-1.5 text-right font-medium">机构</th>
            <th className="px-2 py-1.5 text-right font-medium">题材</th>
            <th className="px-2 py-1.5 text-right font-medium">事件</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr key={c.code} className="border-b border-border/20 hover:bg-muted/10">
              <td className="px-2 py-1.5 text-muted-foreground">{c.rank}</td>
              <td className="px-2 py-1.5 font-mono">{c.code}</td>
              <td className="px-2 py-1.5">{c.name}</td>
              <td className="px-2 py-1.5 text-right font-mono font-bold text-primary">{c.total.toFixed(1)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.sector.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.hot_money.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.seal_strength.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.chip.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.auction.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.northbound.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.institution.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.theme.toFixed(0)}</td>
              <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{c.scores.event.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 战法归因命中标记（占位 Badge——后端 match_strategies 结果 Phase 后补）
export function StrategyMatchBadge({ strategy, matched }: { strategy: string; matched: boolean }) {
  return (
    <Badge variant={matched ? "success" : "default"}>
      {strategy}{matched ? " ✓" : ""}
    </Badge>
  );
}
