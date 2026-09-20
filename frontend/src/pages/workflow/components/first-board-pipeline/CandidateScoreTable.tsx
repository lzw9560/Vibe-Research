// S179 R3.4: FirstBoardPipeline 拆分——候选评分明细表 + 9 维度配置
// §44 诚实标注：9 维度评分未 validated 仅参考；阈值/权重待回测校准。
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import type { FirstBoardCandidate, FirstBoardRawValues } from "@/lib/api";
import { NODE } from "@/components/pipeline/primitives";
import { NODE_DASHED } from "./styles";

// 维度 key 联合类型（与 FirstBoardScoreBreakdown 字段对齐，但用显式字符串避免索引签名 symbol 问题）
type DimKey = "sector" | "hot_money" | "seal_strength" | "chip" | "auction" | "northbound" | "institution" | "theme" | "event";

// ---- 数值格式化工具 ----
/** 金额格式化：元 → 万/亿单位。null → "—" */
function formatAmount(yuan: number | null | undefined): string {
  if (yuan == null) return "—";
  const abs = Math.abs(yuan);
  if (abs >= 1e8) return `${(yuan / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(yuan / 1e4).toFixed(2)}万`;
  return `${yuan.toFixed(0)}`;
}
/** 首封时间格式化：93500 → "09:35"。null → "—" */
function formatSealTime(t: number | null | undefined): string {
  if (t == null) return "—";
  const s = String(t).padStart(6, "0");
  const hh = s.slice(0, 2);
  const mm = s.slice(2, 4);
  return `${hh}:${mm}`;
}

// ---- 9 维度配置（维度名/权重/原始值描述生成器）----
interface DimConfig {
  key: DimKey;
  label: string;
  weight: string;
  /** 生成原始值的人话描述（基于 raw_values 子对象） */
  rawDescribe: (raw: FirstBoardRawValues[DimKey] | undefined) => string;
}

const DIM_CONFIGS: DimConfig[] = [
  {
    key: "sector", label: "板块评分", weight: "15%",
    rawDescribe: (r) => {
      const v = r as { sector_zt_count?: number | null; sector_rank?: number | null } | undefined;
      if (!v) return "—";
      const parts: string[] = [];
      if (v.sector_zt_count != null) parts.push(`板块涨停${v.sector_zt_count}只`);
      if (v.sector_rank != null) parts.push(`排名第${v.sector_rank}`);
      return parts.length ? parts.join("，") : "—";
    },
  },
  {
    key: "hot_money", label: "游资画像", weight: "15%",
    rawDescribe: (r) => {
      const v = r as { seat_risk_label?: string | null; one_day_ratio?: number | null } | undefined;
      if (!v) return "—";
      const parts: string[] = [];
      if (v.seat_risk_label) parts.push(v.seat_risk_label);
      if (v.one_day_ratio != null) parts.push(`一日游占比${(v.one_day_ratio * 100).toFixed(0)}%`);
      return parts.length ? parts.join("，") : "—";
    },
  },
  {
    key: "seal_strength", label: "封板强度", weight: "20%",
    rawDescribe: (r) => {
      const v = r as {
        first_seal?: number | null; seal_amount?: number | null;
        float_cap?: number | null; seal_ratio?: number | null; break_times?: number | null;
      } | undefined;
      if (!v) return "—";
      const parts: string[] = [];
      if (v.first_seal != null) parts.push(`首封${formatSealTime(v.first_seal)}`);
      if (v.seal_amount != null) parts.push(`封单${formatAmount(v.seal_amount)}`);
      if (v.float_cap != null) parts.push(`流通${formatAmount(v.float_cap)}`);
      if (v.seal_ratio != null) parts.push(`比${(v.seal_ratio * 100).toFixed(2)}%`);
      if (v.break_times != null) parts.push(`${v.break_times}炸板`);
      return parts.length ? parts.join("，") : "—";
    },
  },
  {
    key: "chip", label: "筹码结构", weight: "10%",
    rawDescribe: (r) => {
      const v = r as { turnover?: number | null; vol_ratio?: number | null; amount?: number | null } | undefined;
      if (!v) return "—";
      const parts: string[] = [];
      if (v.turnover != null) parts.push(`换手${v.turnover.toFixed(1)}%`);
      if (v.vol_ratio != null) parts.push(`量比${v.vol_ratio.toFixed(2)}`);
      if (v.amount != null) parts.push(`成交${formatAmount(v.amount)}`);
      return parts.length ? parts.join("，") : "—";
    },
  },
  {
    key: "auction", label: "竞价确认", weight: "10%",
    rawDescribe: (r) => {
      const v = r as { auction_open_pct?: number | null; auction_vol_ratio?: number | null } | undefined;
      if (!v) return "—";
      const parts: string[] = [];
      if (v.auction_open_pct != null) parts.push(`高开${(v.auction_open_pct * 100).toFixed(1)}%`);
      if (v.auction_vol_ratio != null) parts.push(`竞价量比${(v.auction_vol_ratio * 100).toFixed(0)}%`);
      return parts.length ? parts.join("，") : "—（T日盘前）";
    },
  },
  {
    key: "northbound", label: "北向资金", weight: "10%",
    rawDescribe: (r) => {
      const v = r as { northbound_net?: number | null } | undefined;
      if (!v) return "—";
      return v.northbound_net != null ? `净流入${formatAmount(v.northbound_net)}` : "—";
    },
  },
  {
    key: "institution", label: "龙虎榜机构", weight: "10%",
    rawDescribe: (r) => {
      const v = r as { inst_net?: number | null } | undefined;
      if (!v) return "—";
      return v.inst_net != null ? `机构净买入${formatAmount(v.inst_net)}` : "—";
    },
  },
  {
    key: "theme", label: "题材热度", weight: "5%",
    rawDescribe: (r) => {
      const v = r as { theme_zt_count?: number | null; theme_name?: string | null } | undefined;
      if (!v) return "—";
      const parts: string[] = [];
      if (v.theme_zt_count != null) parts.push(`同题材涨停${v.theme_zt_count}只`);
      if (v.theme_name) parts.push(`题材"${v.theme_name}"`);
      return parts.length ? parts.join("，") : "—";
    },
  },
  {
    key: "event", label: "事件评分", weight: "5%",
    rawDescribe: (r) => {
      const v = r as { event_type?: string | null; announcement_title?: string | null } | undefined;
      if (!v) return "—";
      const parts: string[] = [];
      if (v.event_type) parts.push(v.event_type);
      if (v.announcement_title) parts.push(v.announcement_title);
      return parts.length ? parts.join("，") : "—";
    },
  },
];

// ---- 候选评分明细表（折叠态一行得分 + 行可展开看"实际值→得分"对照）----
// 可排序的列 key（rank/total 直接取 candidate 字段；其余为 scores 子键）
type SortKey = "rank" | "total" | DimKey;

// 维度列配置（表头显示名 + 对应 scores 子键）
const SCORE_COLS: { key: DimKey; label: string }[] = [
  { key: "sector", label: "板块" },
  { key: "hot_money", label: "游资" },
  { key: "seal_strength", label: "封板" },
  { key: "chip", label: "筹码" },
  { key: "auction", label: "竞价" },
  { key: "northbound", label: "北向" },
  { key: "institution", label: "机构" },
  { key: "theme", label: "题材" },
  { key: "event", label: "事件" },
];

export function CandidateScoreTable({ candidates }: { candidates: FirstBoardCandidate[] }) {
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  // 列头排序 state（默认按 rank 升序——rank 1 是最高分）
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  // 总分筛选滑块 state
  const [minTotal, setMinTotal] = useState(0);

  if (candidates.length === 0) {
    return (
      <div className={NODE_DASHED}>
        <p className="text-xs text-muted-foreground">候选池为空</p>
      </div>
    );
  }

  const toggle = (code: string) => setExpandedCode((prev) => (prev === code ? null : code));

  // 列头点击切换排序
  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // rank 默认升序（1 在前），其余默认降序（高分在前）
      setSortDir(key === "rank" ? "asc" : "desc");
    }
  };

  // 取排序值
  const getSortVal = (c: FirstBoardCandidate, key: SortKey): number => {
    if (key === "rank") return c.rank;
    if (key === "total") return c.total;
    return c.scores?.[key] ?? -1;
  };

  // 排序 + 筛选
  const sorted = [...candidates].sort((a, b) => {
    const av = getSortVal(a, sortKey);
    const bv = getSortVal(b, sortKey);
    return sortDir === "desc" ? bv - av : av - bv;
  });
  const filtered = sorted.filter((c) => c.total >= minTotal);

  // 检查维度是否所有候选都缺失（score=-1 或 undefined）→ 表头加删除线
  const isDimMissing = (dim: DimKey): boolean =>
    candidates.every((c) => {
      const v = c.scores?.[dim];
      return v === -1 || v === undefined || v == null;
    });

  // 排序指示器
  const SortIndicator = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return null;
    return <span className="ml-0.5 text-[9px] text-primary">{sortDir === "desc" ? "▼" : "▲"}</span>;
  };

  // 列头公共样式（可点击排序）
  const thClass = "px-2 py-1.5 text-right font-medium cursor-pointer hover:bg-muted/20 select-none";

  return (
    <div>
      {/* 总分筛选滑块 */}
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs text-amber-400/80">⚠ §44 未验证</span>
        <span className="text-xs text-muted-foreground">总分≥</span>
        <input
          type="range"
          min={0}
          max={100}
          value={minTotal}
          onChange={(e) => setMinTotal(Number(e.target.value))}
          className="w-32 accent-primary"
          aria-label="总分筛选"
        />
        <span className="text-xs font-mono text-primary">{minTotal}</span>
        <span className="text-xs text-muted-foreground">
          （{filtered.length} 只符合
          {filtered.length !== sorted.length && ` / 共 ${sorted.length} 只`}
          ）
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border/40 text-muted-foreground">
              <th className="px-2 py-1.5 text-left font-medium w-6"></th>
              <th
                className="px-2 py-1.5 text-left font-medium cursor-pointer hover:bg-muted/20 select-none"
                onClick={() => toggleSort("rank")}
                title="按排名排序"
              >
                #<SortIndicator col="rank" />
              </th>
              <th className="px-2 py-1.5 text-left font-medium">代码</th>
              <th className="px-2 py-1.5 text-left font-medium">名称</th>
              <th
                className="px-2 py-1.5 text-right font-medium cursor-pointer hover:bg-muted/20 select-none"
                onClick={() => toggleSort("total")}
                title="按总分排序"
              >
                总分<SortIndicator col="total" />
              </th>
              {SCORE_COLS.map((col) => {
                const missing = isDimMissing(col.key);
                return (
                  <th
                    key={col.key}
                    className={cn(thClass, missing && "line-through text-muted-foreground/40")}
                    onClick={() => toggleSort(col.key)}
                    title={missing ? "数据缺失（所有候选 score=-1）· 后续移除或寻找替代" : `按${col.label}排序`}
                  >
                    {col.label}<SortIndicator col={col.key} />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={15} className="px-2 py-4 text-center text-xs text-muted-foreground">
                  无候选符合总分≥{minTotal}（共 {sorted.length} 只）· 调低滑块看更多
                </td>
              </tr>
            ) : (
              filtered.map((c) => {
                const isOpen = expandedCode === c.code;
                const hasRawValues = !!c.raw_values;
                return (
                  <CandidateRowFragment
                    key={c.code}
                    candidate={c}
                    isOpen={isOpen}
                    hasRawValues={hasRawValues}
                    onToggle={() => toggle(c.code)}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// 单个候选的行 + 展开详情卡（两个 <tr>，React Fragment 包裹）
function CandidateRowFragment({
  candidate: c, isOpen, hasRawValues, onToggle,
}: {
  candidate: FirstBoardCandidate;
  isOpen: boolean;
  hasRawValues: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      {/* 主行（可点击展开） */}
      <tr
        onClick={onToggle}
        className={cn(
          "border-b border-border/20 hover:bg-muted/10 cursor-pointer transition-colors",
          isOpen && "bg-muted/15",
        )}
      >
        <td className="px-2 py-1.5 text-muted-foreground text-center">
          <span className="text-xs">{isOpen ? "▼" : "▶"}</span>
        </td>
        <td className="px-2 py-1.5 text-muted-foreground">{c.rank}</td>
        <td className="px-2 py-1.5 font-mono">{c.code}</td>
        <td className="px-2 py-1.5">{c.name}</td>
        <td className="px-2 py-1.5 text-right font-mono font-bold text-primary">{c.total.toFixed(1)}</td>
        {SCORE_COLS.map((col) => {
          const score = c.scores?.[col.key];
          const isMissing = score === -1 || score == null;
          return (
            <td
              key={col.key}
              className={cn(
                "px-2 py-1.5 text-right font-mono",
                isMissing ? "text-muted-foreground/30" : "text-muted-foreground",
              )}
            >
              {isMissing ? "—" : score.toFixed(0)}
            </td>
          );
        })}
      </tr>
      {/* 展开行：详情卡 */}
      {isOpen && (
        <tr>
          <td colSpan={15} className="px-2 pb-3 pt-1">
            <div className={cn(NODE, "bg-muted/5")}>
              {!hasRawValues ? (
                <div className="py-2 text-center text-xs text-muted-foreground">
                  ⚠ 旧快照无原始值（raw_values 未取得）· 仅显示评分，无法展示"实际值→得分"对照
                </div>
              ) : (
                <div className="space-y-1">
                  {DIM_CONFIGS.map((dim) => {
                    const score = c.scores[dim.key];
                    const isMissing = score === -1 || score == null;
                    const rawObj = c.raw_values?.[dim.key];
                    const rawDesc = dim.rawDescribe(rawObj);
                    return (
                      <div
                        key={dim.key}
                        className="flex items-start gap-2 border-b border-border/20 pb-1 last:border-0 last:pb-0"
                      >
                        <span className={cn(
                          "w-20 shrink-0 text-xs font-medium",
                          isMissing ? "text-muted-foreground/40 line-through" : "text-foreground",
                        )}>
                          {dim.label}
                          <span className="ml-1 text-[9px] text-muted-foreground">{dim.weight}</span>
                        </span>
                        <span className="flex-1 text-xs text-muted-foreground">
                          {isMissing ? "数据缺失（score=-1）· 后续移除或寻找替代" : rawDesc}
                        </span>
                        <span className="text-xs text-muted-foreground/40">→</span>
                        <span className={cn(
                          "w-12 shrink-0 text-right font-mono font-bold",
                          isMissing ? "text-muted-foreground/40" : "text-primary",
                        )}>
                          {isMissing ? "—" : `${score.toFixed(0)}分`}
                        </span>
                      </div>
                    );
                  })}
                  <div className="pt-1 text-xs text-muted-foreground">
                    原始值来自后端 raw_values 字段 · 缺失字段标"—" · §44 未 validated 仅参考
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
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
