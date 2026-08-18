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
  FirstBoardCandidate, FirstBoardCandidatesResponse, FirstBoardExcludedItem, FirstBoardRawValues,
} from "@/lib/api";

// 维度 key 联合类型（与 FirstBoardScoreBreakdown 字段对齐，但用显式字符串避免索引签名 symbol 问题）
type DimKey = "sector" | "hot_money" | "seal_strength" | "chip" | "auction" | "northbound" | "institution" | "theme" | "event";

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
  const [ztPoolExpanded, setZtPoolExpanded] = useState(false);
  const [firstBoardExpanded, setFirstBoardExpanded] = useState(false);
  const [excludedExpanded, setExcludedExpanded] = useState(false);
  const [candidatesExpanded, setCandidatesExpanded] = useState(false);
  // 每层剔除子表格独立展开状态（Set<number>，1/2/3 各自可收折；默认全展开方便查看）
  const [expandedLayers, setExpandedLayers] = useState<Set<number>>(new Set([1, 2, 3]));
  const toggleLayer = (layer: number) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layer)) next.delete(layer);
      else next.add(layer);
      return next;
    });
  };

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

  // 每层通过数量反推（基于 excluded 分组 + 候选池总数）
  // 层1 输入 = 首板数；层1 输出 = 首板 - 层1剔除
  // 层2 输入 = 层1输出；层2 输出 = 层2输入 - 层2剔除
  // 层3 输入 = 层2输出；层3 输出 = 候选池总数（层3输出 = 候选池）
  const fbNum = typeof firstBoardCount === "number" ? firstBoardCount : 0;
  const l1Excluded = excludedByLayer[1].length;
  const l2Excluded = excludedByLayer[2].length;
  const l1Output = Math.max(fbNum - l1Excluded, 0);
  const l2Output = Math.max(l1Output - l2Excluded, 0);
  const l3Output = candidates.length; // 层3 输出 = 候选池

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
  // 每层 input→output 用于 FunnelShrinkBar
  const layerFunnel: Record<number, { input: number; output: number }> = {
    1: { input: fbNum, output: l1Output },
    2: { input: l1Output, output: l2Output },
    3: { input: l2Output, output: l3Output },
  };

  // 统一展开指示器
  const ExpandIndicator = ({ open }: { open: boolean }) => (
    <span className="text-[10px] text-muted-foreground">{open ? "▼ 收起" : "▶ 展开"}</span>
  );

  return (
    <div className="space-y-1">
      {/* 涨停股池（可展开——API 仅返回汇总数，展开诚实降级） */}
      <button
        onClick={() => setZtPoolExpanded((v) => !v)}
        className={cn(NODE_GREEN, "w-full text-left hover:bg-emerald-500/10")}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">涨停股池</div>
            <div className="text-[11px] text-muted-foreground">em_zt_topic_pool · T日涨停 → 选 T+1</div>
          </div>
          <div className="flex items-center gap-2">
            <div className="text-lg font-bold text-emerald-400">{ztPoolCount}</div>
            <ExpandIndicator open={ztPoolExpanded} />
          </div>
        </div>
      </button>
      {ztPoolExpanded && (
        <div className="ml-2 border-l-2 border-emerald-500/30 pl-3">
          <div className={cn(NODE_DASHED, "border-emerald-500/30 bg-emerald-500/5")}>
            <div className="text-[11px] font-medium text-emerald-300">涨停池明细数据未取得</div>
            <p className="mt-1 text-[10px] text-muted-foreground/70">
              API 仅返回 <code className="rounded bg-muted/30 px-1">zt_pool_count</code> 汇总数，
              不含涨停池标的明细（code/name/lbc）。明细数据需后端补 <code className="rounded bg-muted/30 px-1">zt_pool_items</code> 字段后接入。
            </p>
            <p className="mt-1 text-[10px] text-muted-foreground/50">
              此处不臆造标的列表——诚实标注数据缺失。
            </p>
          </div>
        </div>
      )}
      <ArrowDown label="lbc=1 首板过滤" />

      {/* 首板过滤（可展开——API 仅返回汇总数，展开诚实降级 + 链接到三层剔除看明细） */}
      <button
        onClick={() => setFirstBoardExpanded((v) => !v)}
        className={cn(NODE_GREEN, "w-full text-left hover:bg-emerald-500/10")}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">首板过滤</div>
            <div className="text-[11px] text-muted-foreground">连板数 lbc=1（首板涨停）</div>
          </div>
          <div className="flex items-center gap-2">
            <div className="text-lg font-bold text-emerald-400">{firstBoardCount}</div>
            <ExpandIndicator open={firstBoardExpanded} />
          </div>
        </div>
      </button>
      {firstBoardExpanded && (
        <div className="ml-2 border-l-2 border-emerald-500/30 pl-3">
          <div className={cn(NODE_DASHED, "border-emerald-500/30 bg-emerald-500/5")}>
            <div className="text-[11px] font-medium text-emerald-300">首板明细数据未取得</div>
            <p className="mt-1 text-[10px] text-muted-foreground/70">
              API 返回 <code className="rounded bg-muted/30 px-1">first_board_count</code> 汇总数，
              但不含首板过滤产出明细。下游可见的是三层剔除后的 <b className="text-foreground">候选池（{candidates.length} 只）</b>
              + <b className="text-destructive">剔除记录（{excluded.length} 只）</b>。
            </p>
            <p className="mt-1 text-[10px] text-muted-foreground/50">
              ⚠ 候选 + 剔除 ≠ 首板数（三层剔除是串联过滤，剔除记录按层累加）。
              反推不完全准确，故不展示反推列表。
            </p>
            <button
              type="button"
              onClick={() => { setExcludedExpanded(true); setFirstBoardExpanded(false); }}
              className="mt-1.5 text-[10px] text-primary hover:underline"
            >
              → 展开三层剔除节点看候选+剔除明细
            </button>
          </div>
        </div>
      )}
      <ArrowDown label="3 层剔除" />

      {/* 三层剔除节点（可展开——增强：每层通过数量 + FunnelShrinkBar + 剔除明细） */}
      <button
        onClick={() => setExcludedExpanded((v) => !v)}
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
            <ExpandIndicator open={excludedExpanded} />
          </div>
        </div>
        <div className="mt-1 text-[11px] text-muted-foreground/80">
          共剔除 {excluded.length} 只 · 点展开看每层通过数 + 分层剔除原因
        </div>
      </button>

      {excludedExpanded && (
        <div className="space-y-2 border-t border-border/30 pt-2">
          {/* 总收缩条（首板→候选池） */}
          <FunnelShrinkBar
            input={typeof firstBoardCount === "number" ? firstBoardCount : 0}
            output={candidates.length}
          />
          {[1, 2, 3].map((layer) => {
            const layerOpen = expandedLayers.has(layer);
            return (
              <div key={layer}>
                {/* 每层通过数量 + 收缩条（总览） */}
                <div className={cn(NODE, "mb-1.5")}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-foreground">
                      {layerNames[layer]}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      通过 {layerFunnel[layer].output} 只
                      <span className="text-muted-foreground/40"> / 剔除 {excludedByLayer[layer].length}</span>
                    </span>
                  </div>
                  <div className="mt-1.5">
                    <FunnelShrinkBar
                      input={layerFunnel[layer].input}
                      output={layerFunnel[layer].output}
                    />
                  </div>
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    {layerReasons[layer]}
                  </div>
                </div>
                {/* 该层剔除明细子表格（可收折） */}
                {excludedByLayer[layer].length > 0 && (
                  <div className={cn(NODE_RED, "opacity-90")}>
                    {/* 表头行：点击收折 */}
                    <button
                      type="button"
                      onClick={() => toggleLayer(layer)}
                      className="flex w-full items-center justify-between text-left hover:opacity-80"
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] text-destructive">{layerOpen ? "▼" : "▶"}</span>
                        <span className="text-[11px] font-medium text-destructive">
                          {layerNames[layer]} · 剔除明细
                        </span>
                      </div>
                      <span className="text-[10px] text-destructive">
                        {excludedByLayer[layer].length} 只
                      </span>
                    </button>
                    {/* 展开后渲染表格 */}
                    {layerOpen && (
                      <table className="mt-2 w-full text-xs">
                        <thead>
                          <tr className="border-b border-border/40 text-muted-foreground">
                            <th className="px-2 py-1 text-left font-medium">代码</th>
                            <th className="px-2 py-1 text-left font-medium">名称</th>
                            <th className="px-2 py-1 text-left font-medium">剔除原因</th>
                          </tr>
                        </thead>
                        <tbody>
                          {excludedByLayer[layer].map((e) => (
                            <tr
                              key={e.code}
                              className="border-b border-border/20 hover:bg-muted/10"
                            >
                              <td className="px-2 py-1 font-mono text-destructive">{e.code}</td>
                              <td className="px-2 py-1 text-muted-foreground/50">—</td>
                              <td className="px-2 py-1 text-destructive/80">{e.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <ArrowDown label="9 维度评分" />

      {/* 候选池（可展开——展示 9 维度评分表） */}
      <button
        onClick={() => setCandidatesExpanded((v) => !v)}
        className={cn(NODE, "w-full text-left hover:bg-card/60")}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">候选池</div>
            <div className="text-[11px] text-muted-foreground">9 维度加权评分 · 降序</div>
          </div>
          <div className="flex items-center gap-2">
            <div className="text-lg font-bold text-primary">{candidates.length}</div>
            <ExpandIndicator open={candidatesExpanded} />
          </div>
        </div>
      </button>
      {candidatesExpanded && (
        <div className="border-t border-border/30 pt-2">
          <CandidateScoreTable candidates={candidates} />
        </div>
      )}
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

// ---- 盯盘手册（spec 2.3 时刻表，②确认节点用）----
// 5 个时段 × 4 列（时刻/工具提供/人工观察/决策）。静态 spec 内容，无 API 数据。
// 当前时段高亮（绿底），盘后/非交易时段不高亮，诚实标注。
const WATCHBOOK_SLOTS = [
  {
    id: "s1",
    time: "9:15-9:20",
    tool: "竞价价/量推送",
    watch: "大单是否可撤（诱饵识别）",
    decision: "只看不动",
  },
  {
    id: "s2",
    time: "9:20-9:25",
    tool: "竞价价/量（不可撤）",
    watch: "量价是否匹配",
    decision: "竞价确认",
  },
  {
    id: "s3",
    time: "9:25",
    tool: "竞价收盘价推送",
    watch: "高开1-3%→健康 / >5%追高",
    decision: "✅确认/❌放弃",
  },
  {
    id: "s4",
    time: "9:30-9:35",
    tool: "开盘价+5分钟K线推送",
    watch: "5分钟不破开盘价",
    decision: "✅买盘支撑",
  },
  {
    id: "s5",
    time: "9:35-9:45",
    tool: "候选逐只确认状态推送",
    watch: "买一档挂单量 vs 卖一档",
    decision: "买>卖→建仓",
  },
] as const;

/** 判断当前在哪个盯盘时段（北京时间 9:15-9:45）。返回 slot id 或 null（盘后/非交易时段）。
 *  用浏览器本地时间——诚实标注：前端无法取得北京 tz 后端时间，盯盘手册是辅助参考，
 *  时段高亮仅供视觉引导，非精确交易时段判定（后端 Phase 2 接入后可用 backend current_time）。 */
function currentWatchbookSlot(): string | null {
  const now = new Date();
  const day = now.getDay(); // 0=周日, 6=周六
  if (day === 0 || day === 6) return null; // 周末非交易
  // 北京时间 UTC+8；浏览器可能在其他 tz。盯盘手册是 9:15-9:45 北京时间。
  // 取 UTC 分钟数 + 8h offset，mod 1440 得北京时间分钟数。
  const utcMin = now.getUTCHours() * 60 + now.getUTCMinutes();
  const bjMin = (utcMin + 8 * 60) % 1440;
  // 9:15=555, 9:20=560, 9:25=565, 9:30=570, 9:35=575, 9:45=585
  if (bjMin >= 555 && bjMin < 560) return "s1";
  if (bjMin >= 560 && bjMin < 565) return "s2";
  if (bjMin >= 565 && bjMin < 570) return "s3";
  if (bjMin >= 570 && bjMin < 575) return "s4";
  if (bjMin >= 575 && bjMin < 585) return "s5";
  return null;
}

function WatchbookManual() {
  const [expanded, setExpanded] = useState(false);
  const currentSlot = currentWatchbookSlot();
  const currentSlotData = WATCHBOOK_SLOTS.find((s) => s.id === currentSlot) ?? null;

  // 缩略态文案：当前时段 or 盘后/非交易时段
  const summaryText = currentSlotData
    ? `当前：${currentSlotData.time} · ${currentSlotData.decision}`
    : "盘后/非交易时段";

  return (
    <div className="mt-2">
      {/* 缩略行（可点击展开） */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(NODE_AMBER, "w-full text-left hover:bg-amber-500/10")}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-[11px]">⏱</span>
            <span className="text-xs font-medium text-amber-200">盯盘手册 9:15-9:45</span>
            <span className="text-[10px] text-muted-foreground/60">5 个时段</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn(
              "text-[10px]",
              currentSlotData ? "text-emerald-400" : "text-muted-foreground/50",
            )}>
              {summaryText}
            </span>
            <span className="text-[10px] text-muted-foreground">
              {expanded ? "▼ 收起" : "▶ 展开"}
            </span>
          </div>
        </div>
      </button>

      {/* 详情态：5 行 4 列 grid 时刻表 */}
      {expanded && (
        <div className="mt-1.5 border-t border-amber-500/20 pt-2">
          {/* 表头 */}
          <div className="grid grid-cols-[80px_1fr_1fr_1fr] gap-1 border-b border-border/40 pb-1 text-[10px] font-medium text-muted-foreground">
            <span>时刻</span>
            <span>工具提供（自动）</span>
            <span>人工观察（盯盘）</span>
            <span>决策</span>
          </div>
          {/* 5 行时段 */}
          {WATCHBOOK_SLOTS.map((slot) => {
            const isCurrent = slot.id === currentSlot;
            return (
              <div
                key={slot.id}
                className={cn(
                  "grid grid-cols-[80px_1fr_1fr_1fr] gap-1 rounded px-1 py-1 text-[10px] transition-colors",
                  isCurrent
                    ? "bg-emerald-500/15 ring-1 ring-emerald-500/40"
                    : "bg-muted/5",
                )}
              >
                <span className={cn("font-mono", isCurrent ? "text-emerald-300 font-bold" : "text-muted-foreground")}>
                  {isCurrent && "▶ "}{slot.time}
                </span>
                <span className="text-muted-foreground">{slot.tool}</span>
                <span className="text-muted-foreground">{slot.watch}</span>
                <span className={isCurrent ? "text-foreground font-medium" : "text-muted-foreground"}>
                  {slot.decision}
                </span>
              </div>
            );
          })}
          {/* 诚实标注 */}
          <p className="mt-1.5 text-[10px] text-muted-foreground/50">
            {currentSlotData
              ? `当前时段高亮（绿底）· 时段判定用浏览器时间，后端 Phase 2 接入后改用 backend current_time 北京 tz`
              : "盘后/非交易时段，不高亮 · 时段判定用浏览器时间，后端 Phase 2 接入后改用 backend current_time 北京 tz"}
          </p>
        </div>
      )}
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
      {/* 盯盘手册（spec 2.3 时刻表，缩略+点开看详情） */}
      <WatchbookManual />
      <div className="mt-2 text-[10px] text-muted-foreground/70">
        逐只状态：待确认 → 确认中 → ✅/❌（Phase 2 竞价+开盘确认后接入）
      </div>
    </div>
  );
}

// ---- ③ 候选推荐节点（展示全部候选，不替用户做决定）----
function PositionNode({ data }: { data: FirstBoardCandidatesResponse | null }) {
  const candidates = data?.candidates ?? [];
  return (
    <div className={candidates.length > 0 ? NODE : NODE_DASHED}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">③ 候选推荐</div>
          <div className="text-[11px] text-muted-foreground">全部候选 · 评分排序 · 推荐参考不替用户做决定</div>
        </div>
        <span className="rounded bg-primary/20 px-1 text-[10px] text-primary">
          {candidates.length > 0 ? `全部 ${candidates.length} 只` : "待 Phase 3"}
        </span>
      </div>
      {candidates.length > 0 ? (
        <div className="mt-2 space-y-1">
          {/* 候选超过 20 只时限制高度可滚动，避免节点过长 */}
          <div className={candidates.length > 20 ? "max-h-60 space-y-1 overflow-y-auto pr-1" : "space-y-1"}>
            {candidates.map((c) => (
              <div key={c.code} className="flex items-center justify-between text-[11px]">
                <span className="text-foreground">
                  #{c.rank} {c.code} {c.name}
                </span>
                <span className="font-mono text-primary">{c.total.toFixed(1)}</span>
              </div>
            ))}
          </div>
          <div className="mt-1 text-[10px] text-muted-foreground/60">
            ⚠ 推荐参考，不替用户做决定 · 风控：止损 −3% / 止盈 +5% / T+1 必卖
          </div>
          <div className="text-[10px] text-amber-200/60">
            §44 未 validated 仅参考；阈值/权重待回测校准
          </div>
        </div>
      ) : (
        <div className="mt-2 text-[10px] text-muted-foreground/60">
          候选池为空
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
export function CandidateScoreTable({ candidates }: { candidates: FirstBoardCandidate[] }) {
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  if (candidates.length === 0) {
    return (
      <div className={NODE_DASHED}>
        <p className="text-xs text-muted-foreground">候选池为空</p>
      </div>
    );
  }

  const toggle = (code: string) => setExpandedCode((prev) => (prev === code ? null : code));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border/40 text-muted-foreground">
            <th className="px-2 py-1.5 text-left font-medium w-6"></th>
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
          {candidates.map((c) => {
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
          })}
        </tbody>
      </table>
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
          <span className="text-[10px]">{isOpen ? "▼" : "▶"}</span>
        </td>
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
      {/* 展开行：详情卡 */}
      {isOpen && (
        <tr>
          <td colSpan={15} className="px-2 pb-3 pt-1">
            <div className={cn(NODE, "bg-muted/5")}>
              {!hasRawValues ? (
                <div className="py-2 text-center text-[11px] text-muted-foreground/60">
                  ⚠ 旧快照无原始值（raw_values 未取得）· 仅显示评分，无法展示"实际值→得分"对照
                </div>
              ) : (
                <div className="space-y-1">
                  {DIM_CONFIGS.map((dim) => {
                    const score = c.scores[dim.key];
                    const rawObj = c.raw_values?.[dim.key];
                    const rawDesc = dim.rawDescribe(rawObj);
                    return (
                      <div
                        key={dim.key}
                        className="flex items-start gap-2 border-b border-border/20 pb-1 last:border-0 last:pb-0"
                      >
                        <span className="w-20 shrink-0 text-[11px] font-medium text-foreground">
                          {dim.label}
                          <span className="ml-1 text-[9px] text-muted-foreground/50">{dim.weight}</span>
                        </span>
                        <span className="flex-1 text-[11px] text-muted-foreground">
                          {rawDesc}
                        </span>
                        <span className="text-[11px] text-muted-foreground/40">→</span>
                        <span className="w-12 shrink-0 text-right font-mono font-bold text-primary">
                          {score.toFixed(0)}分
                        </span>
                      </div>
                    );
                  })}
                  <div className="pt-1 text-[10px] text-muted-foreground/50">
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
