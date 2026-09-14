// S179 Phase 2: /intraday 盘中 cockpit 页——SplitLayout（左候选列表+右个股预览+告警+教练）
// + OFI 看板（接 S178 OfiDashboard）+ honest empty（盘中无数据不假装）。
// 盘中"有位置没数据"——edge 在未测盘中 60%（push2his IP 封+hithink 有限），
// cockpit 可能长期 honest empty state（HonestEmptyState 如实呈现无数据）。
// deferred：盘中实时行情/OFI/告警/教练数据均未测（§44 选股层证否，edge 在未测盘中盘口博弈）。
// 接 S176 OFI 采集器（已采数据）+ S178 OfiDashboard + Phase 0 SplitLayout/HonestEmptyState/currentStock。
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { RefreshCw, Lightbulb, Clock, Activity } from "lucide-react";
import { SplitLayout } from "@/components/layout/SplitLayout";
import { OfiDashboard } from "@/components/intraday/OfiDashboard";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { BombAlertBanner } from "@/components/risk/BombAlertBanner";
import { PageHeader } from "@/components/ui/PageHeader";
import { FocusDayStrip } from "@/components/ui/FocusDayStrip";
import { GlassCard } from "@/components/ui/GlassCard";
import { TabBar } from "@/components/ui/TabBar";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { cn, pctColor } from "@/lib/utils";
import { useCurrentStock, useSelectStock } from "@/stores/currentStock";
import { useFocusDay } from "@/stores/focusDay";
import {
  useDateTriplet,
  useEmotion,
  useIntradayLatest,
  useQuote,
  useCoachStatus,
  useCoachTimetable,
} from "@/lib/query";
import { usePremarketSelection, type PremarketCandidate } from "@/lib/query/premarket";
import type { LianbanStock, CoachTimetableSlot, CoachChecklistItem } from "@/lib/api";

// SplitLayout 高度——留 OFI 看板 + 页头空间（同 StockCockpit COCKPIT_HEIGHT 范式）
const COCKPIT_HEIGHT = "h-[calc(100vh-22rem)] min-h-[400px]";

const CANDIDATE_TABS = [
  { key: "breakout", label: "盘前选股" },
  { key: "lianban", label: "涨停池" },
];

// ─── 格式化（复用 StockCockpit 范式）──────────────────────────────────────

const fmtPrice = (v: number | null | undefined): string =>
  v == null ? "—" : v.toFixed(2);

const fmtPct = (v: number | null | undefined): string =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

const fmtAmount = (v: number | null | undefined): string => {
  if (v == null) return "—";
  if (v >= 1e8) return (v / 1e8).toFixed(1) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
  return v.toFixed(0);
};

// ═════════════════════════════════════════════════════════════════════════
// IntradayCockpit — 主 cockpit 页
// ═════════════════════════════════════════════════════════════════════════

export function IntradayCockpit() {
  const { focusDate } = useFocusDay();
  const { data: triplet } = useDateTriplet(focusDate ?? undefined);
  const [tab, setTab] = useState("breakout");
  const { code: curCode, name: curName } = useCurrentStock();
  const selectStock = useSelectStock();

  const isTradingDay = triplet?.is_trading_day ?? true;
  const today = triplet?.today ?? new Date().toISOString().slice(0, 10);

  // 候选列表数据源
  // deferred：breakout §44 naive lift=1.36x <2x 非 validated；lianban 来自 useEmotion
  const premarketQ = usePremarketSelection(today, 20, 0.9);
  const emotionQ = useEmotion();
  const latestQ = useIntradayLatest();
  const coachStatusQ = useCoachStatus();
  const timetableQ = useCoachTimetable();

  const premarketCandidates = premarketQ.data?.candidates ?? [];
  const lianbanStocks: LianbanStock[] = emotionQ.data?.lianban_stocks ?? [];
  const latest = latestQ.data;

  const coachStatus = coachStatusQ.data;
  const slots = timetableQ.data?.slots ?? [];
  const currentSlotId =
    timetableQ.data?.current_slot_id ??
    coachStatus?.current_slot?.slot_id ??
    null;
  const currentSlot = slots.find((s) => s.slot_id === currentSlotId) ?? null;
  const checklist = coachStatus?.checklist ?? [];
  const slotStatus = coachStatus?.slot_status ?? "before_open";
  const currentTime = coachStatus?.current_time ?? "--:--";

  // 问 AI 上下文——注入 cockpit 真实数据（仿 IntradayMonitor buildIntradayContext）
  const askAiContext = [
    `当前页面：盘中 cockpit`,
    `交易日：${isTradingDay ? "是" : "否"}，今日=${today}，阶段=${triplet?.stage ?? "未知"}`,
    latest
      ? `盘中情绪：涨停${latest.zt_count ?? "--"}/封板率${latest.seal_rate != null ? latest.seal_rate.toFixed(0) + "%" : "--"}/炸板率${latest.break_rate != null ? latest.break_rate.toFixed(0) + "%" : "--"}/涨跌比${latest.ad_ratio != null ? latest.ad_ratio.toFixed(2) : "--"}，分数=${latest.score ?? "--"}/${latest.zone}`
      : `盘中情绪：未取得`,
    `盘前选股候选：${premarketCandidates.length} 只（breakout 弱信号 §44 lift<2x）`,
    `涨停池：${lianbanStocks.length} 只`,
    `盯盘教练：${currentSlot?.label ?? "无环节"}（${slotStatus}）`,
    `预警：${checklist.filter((c) => c.bomb_alerts.length > 0).length} 只有炸板预警`,
  ].join("\n");

  const refreshAll = () => {
    void premarketQ.refetch();
    void emotionQ.refetch();
    void latestQ.refetch();
    void coachStatusQ.refetch();
    void timetableQ.refetch();
  };

  return (
    <div>
      <PageHeader
        title="盘中 cockpit"
        subtitle="候选列表 + 个股预览 + OFI + 告警 + 教练 · 盘中数据 60% 未测，honest empty 不假装"
        actions={
          <div className="flex items-center gap-3">
            <FocusDayStrip />
            <AskAiButton context={askAiContext} label="问 AI" />
            <button
              onClick={refreshAll}
              className="text-muted-foreground hover:text-primary"
              title="刷新全部"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        }
      />

      {/* honest banner：盘中数据 60% 未测 */}
      <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-600 dark:text-amber-400">
        盘中数据 60% 未测（edge 在未测盘中盘口博弈）· OFI / 告警 / 教练如实呈现，无数据时显示空态不假装
      </div>

      {/* 非交易日 honest empty */}
      {!isTradingDay && (
        <div className="mb-4">
          <HonestEmptyState
            message="今日非交易日，盘中数据暂停采集"
            hint="交易日盘中开盘后恢复 OFI / 涨停池 / 教练数据"
          />
        </div>
      )}

      {/* SplitLayout: 左候选列表 + 右个股预览+告警+教练 */}
      <div className={COCKPIT_HEIGHT}>
        <SplitLayout
          left={
            <CandidateList
              tab={tab}
              onTabChange={setTab}
              premarketCandidates={premarketCandidates}
              premarketLoading={premarketQ.isLoading}
              premarketError={premarketQ.error != null}
              lianbanStocks={lianbanStocks}
              lianbanLoading={emotionQ.isLoading}
              selectedCode={curCode}
              onSelect={(code, name) =>
                selectStock(code, name ?? undefined, "intraday")
              }
              isTradingDay={isTradingDay}
            />
          }
          right={
            <RightPanel
              curCode={curCode}
              curName={curName}
              currentSlot={currentSlot}
              slotStatus={slotStatus}
              currentTime={currentTime}
              checklist={checklist}
            />
          }
          storageKey="vr-intraday-cockpit"
          defaultWidth={340}
        />
      </div>

      {/* OFI 看板（S178，read-only，非信号） */}
      <div className="mb-6">
        <h3 className="mb-2 text-sm font-semibold text-muted-foreground">
          OFI 盘中数据看板（read-only · 非信号）
        </h3>
        <OfiDashboard />
      </div>

      <Disclaimer />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// CandidateList — 左栏：盘前选股 + 涨停池候选
// ═════════════════════════════════════════════════════════════════════════

interface CandidateListProps {
  tab: string;
  onTabChange: (key: string) => void;
  premarketCandidates: PremarketCandidate[];
  premarketLoading: boolean;
  premarketError: boolean;
  lianbanStocks: LianbanStock[];
  lianbanLoading: boolean;
  selectedCode: string | null;
  onSelect: (code: string, name: string | null) => void;
  isTradingDay: boolean;
}

function CandidateList({
  tab,
  onTabChange,
  premarketCandidates,
  premarketLoading,
  premarketError,
  lianbanStocks,
  lianbanLoading,
  selectedCode,
  onSelect,
  isTradingDay,
}: CandidateListProps) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border p-2">
        <TabBar tabs={CANDIDATE_TABS} activeKey={tab} onChange={onTabChange} size="sm" />
      </div>
      <div className="flex-1 overflow-auto">
        {tab === "breakout" ? (
          <BreakoutList
            candidates={premarketCandidates}
            loading={premarketLoading}
            error={premarketError}
            selectedCode={selectedCode}
            onSelect={onSelect}
            isTradingDay={isTradingDay}
          />
        ) : (
          <LianbanList
            stocks={lianbanStocks}
            loading={lianbanLoading}
            selectedCode={selectedCode}
            onSelect={onSelect}
            isTradingDay={isTradingDay}
          />
        )}
      </div>
    </div>
  );
}

// ─── breakout 候选列表 ──────────────────────────────────────────────────

function BreakoutList({
  candidates,
  loading,
  error,
  selectedCode,
  onSelect,
  isTradingDay,
}: {
  candidates: PremarketCandidate[];
  loading: boolean;
  error: boolean;
  selectedCode: string | null;
  onSelect: (code: string, name: string | null) => void;
  isTradingDay: boolean;
}) {
  if (loading) {
    return <div className="p-4 text-center text-sm text-muted-foreground">加载中…</div>;
  }
  if (error) {
    return (
      <HonestEmptyState
        message="盘前选股数据加载失败"
        hint={
          <span>
            端点 <code className="font-mono">/strategy/premarket-selection</code> 未取得
          </span>
        }
      />
    );
  }
  if (candidates.length === 0) {
    return (
      <HonestEmptyState
        message="暂无盘前选股候选"
        hint={
          <span>
            breakout 弱信号（§44 naive lift=1.36x &lt;2x 非 validated）·
            {isTradingDay ? "今日无满足条件的候选" : "非交易日，盘前选股暂停"}
          </span>
        }
      />
    );
  }
  return (
    <div className="divide-y divide-border/40">
      {candidates.map((c) => (
        <BreakoutRow
          key={c.code}
          candidate={c}
          isSelected={c.code === selectedCode}
          onSelect={() => onSelect(c.code, c.name)}
        />
      ))}
    </div>
  );
}

function BreakoutRow({
  candidate: c,
  isSelected,
  onSelect,
}: {
  candidate: PremarketCandidate;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const navigate = useNavigate();
  return (
    <button
      onClick={onSelect}
      className={`flex w-full flex-col gap-1 px-3 py-2 text-left hover:bg-muted/30 ${
        isSelected ? "border-l-2 border-l-primary bg-primary/10" : ""
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-medium">{c.code}</span>
          <span className="truncate text-xs text-muted-foreground">{c.name}</span>
        </div>
        <span
          className={`font-mono text-xs ${c.breakout_binary ? "text-emerald-500" : "text-muted-foreground"}`}
        >
          {c.breakout_score.toFixed(3)}{c.breakout_binary ? " ●" : ""}
        </span>
      </div>
      <div className="flex gap-3 text-[11px] text-muted-foreground/70">
        <span>入场 {fmtPrice(c.entry_ref)}</span>
        <span className="text-red-500/70">止损 {fmtPrice(c.stop_loss)}</span>
        <span className="text-emerald-500/70">止盈 {fmtPrice(c.take_profit)}</span>
      </div>
      {/* Track E A8: 因子→§44 verdict 直达（breakout 候选→breakout 维度 verdict） */}
      <div className="mt-0.5 text-right">
        <span
          role="link"
          tabIndex={0}
          onClick={(e) => { e.stopPropagation(); navigate("/review?tab=validation"); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); navigate("/review?tab=validation"); } }}
          className="cursor-pointer text-[10px] text-primary hover:underline"
        >
          查 §44 verdict →
        </span>
      </div>
    </button>
  );
}

// ─── 涨停池候选列表 ─────────────────────────────────────────────────────

function LianbanList({
  stocks,
  loading,
  selectedCode,
  onSelect,
  isTradingDay,
}: {
  stocks: LianbanStock[];
  loading: boolean;
  selectedCode: string | null;
  onSelect: (code: string, name: string | null) => void;
  isTradingDay: boolean;
}) {
  if (loading) {
    return <div className="p-4 text-center text-sm text-muted-foreground">加载中…</div>;
  }
  if (stocks.length === 0) {
    return (
      <HonestEmptyState
        message="暂无涨停股"
        hint={isTradingDay ? "盘中开盘后涨停池实时更新" : "非交易日，涨停池暂停"}
      />
    );
  }
  return (
    <div className="divide-y divide-border/40">
      {stocks.map((s, i) => (
        <LianbanRow
          key={`${s.code}-${i}`}
          stock={s}
          isSelected={s.code === selectedCode}
          onSelect={() => onSelect(s.code, s.name)}
        />
      ))}
    </div>
  );
}

function LianbanRow({
  stock: s,
  isSelected,
  onSelect,
}: {
  stock: LianbanStock;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`flex w-full items-center justify-between px-3 py-2 text-left hover:bg-muted/30 ${
        isSelected ? "border-l-2 border-l-primary bg-primary/10" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        {s.boards != null && s.boards > 0 && (
          <span className="rounded bg-amber-500/15 px-1 text-[10px] font-bold text-amber-600 dark:text-amber-400">
            {s.boards}板
          </span>
        )}
        <span className="font-mono text-sm font-medium">{s.code}</span>
        <span className="truncate text-xs text-muted-foreground">{s.name ?? "—"}</span>
      </div>
      <div className="flex items-center gap-2 text-xs">
        <span className="font-mono text-muted-foreground/70">{fmtAmount(s.amount)}</span>
        <span className={cn("font-mono", pctColor(s.pct))}>{fmtPct(s.pct)}</span>
      </div>
    </button>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// RightPanel — 右栏：告警 + 个股预览 + 教练
// ═════════════════════════════════════════════════════════════════════════

interface RightPanelProps {
  curCode: string | null;
  curName: string | null;
  currentSlot: CoachTimetableSlot | null;
  slotStatus: string;
  currentTime: string;
  checklist: CoachChecklistItem[];
}

function RightPanel({
  curCode,
  curName,
  currentSlot,
  slotStatus,
  currentTime,
  checklist,
}: RightPanelProps) {
  return (
    <div className="space-y-4 p-4">
      {/* 告警流——BombAlertBanner 接现有（自管数据 fetch，无告警返 null 不占空间） */}
      <BombAlertBanner />

      {/* 个股预览——selected code 或 HonestEmptyState */}
      <StockPreview code={curCode} name={curName} />

      {/* 教练紧凑视图 */}
      <IntradayCoachCompact
        currentSlot={currentSlot}
        slotStatus={slotStatus}
        currentTime={currentTime}
        checklist={checklist}
      />
    </div>
  );
}

// ─── 个股预览（无 code → HonestEmptyState；有 code → useQuote 轻量预览）─────

function StockPreview({
  code,
  name,
}: {
  code: string | null;
  name: string | null;
}) {
  // 无 code：诚实空态（不假装有预览）
  if (!code) {
    return (
      <HonestEmptyState
        message="请从左侧选择候选"
        hint="盘前选股 / 涨停池候选点击后在此预览个股行情"
      />
    );
  }
  // 有确定 code 才调 useQuote（独立组件避免条件 hook，同 StockCockpit 范式）
  return <StockPreviewContent code={code} name={name} />;
}

function StockPreviewContent({
  code,
  name,
}: {
  code: string;
  name: string | null;
}) {
  const quoteQ = useQuote(code);
  const quote = quoteQ.data?.[code] ?? null;

  return (
    <GlassCard className="p-4">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-lg font-bold">{code}</span>
          {name && <span className="text-sm text-muted-foreground">{name}</span>}
        </div>
        <Link to={`/stock/${code}`} className="text-xs text-primary hover:underline">
          详情 →
        </Link>
      </div>

      {quote ? (
        <div className="mt-2 flex items-baseline gap-3">
          <span className="font-mono text-xl font-bold">{fmtPrice(quote.price)}</span>
          <span className={cn("text-sm font-mono", pctColor(quote.change_pct))}>
            {fmtPct(quote.change_pct)}
          </span>
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          {quoteQ.isLoading
            ? "加载中…"
            : "行情未取得（盘中实时行情有限，不臆造）"}
        </p>
      )}
    </GlassCard>
  );
}

// ─── 教练紧凑视图（当前环节 + 教学点 + 清单摘要 + 链接）──────────────────

function IntradayCoachCompact({
  currentSlot,
  slotStatus,
  currentTime,
  checklist,
}: {
  currentSlot: CoachTimetableSlot | null;
  slotStatus: string;
  currentTime: string;
  checklist: CoachChecklistItem[];
}) {
  const watchingCount = checklist.filter((c) => c.status === "watching").length;
  const monitoringCount = checklist.filter((c) => c.status === "monitoring").length;
  const holdingCount = checklist.filter((c) => c.status === "holding").length;
  const bombCount = checklist.filter((c) => c.bomb_alerts.length > 0).length;

  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Clock className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">盯盘教练</h3>
        </div>
        <Link to="/workflow/coach" className="text-xs text-primary hover:underline">
          全部 →
        </Link>
      </div>

      {/* 当前环节 */}
      {currentSlot ? (
        <div className="mb-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-mono text-xs text-muted-foreground">
              {currentSlot.start}–{currentSlot.end}
            </span>
            <span className="font-medium">{currentSlot.label}</span>
            <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] text-primary">
              {slotStatusLabel(slotStatus)}
            </span>
          </div>
          {currentSlot.teaching && (
            <div className="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground">
              <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
              <span>{currentSlot.teaching}</span>
            </div>
          )}
        </div>
      ) : (
        <HonestEmptyState
          message="暂无盯盘教练数据"
          hint="盘前生成时刻表后显示当前环节 + 教学点"
          className="mb-3"
        />
      )}

      {/* 清单摘要 */}
      <div className="flex items-center gap-3 text-xs">
        <div className="flex items-center gap-1">
          <Activity className="h-3 w-3 text-muted-foreground" />
          <span className="text-muted-foreground">候选</span>
          <span className="font-mono font-medium">
            {watchingCount}/{monitoringCount}/{holdingCount}
          </span>
          <span className="text-muted-foreground/50">（观/盯/持）</span>
        </div>
        {bombCount > 0 && (
          <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] text-red-500">
            炸板预警 {bombCount}
          </span>
        )}
      </div>

      <p className="mt-2 text-[11px] text-muted-foreground/50">
        当前时间 {currentTime}
      </p>
    </GlassCard>
  );
}

// ─── 辅助 ────────────────────────────────────────────────────────────────

function slotStatusLabel(s: string): string {
  switch (s) {
    case "active":
      return "进行中";
    case "gap":
      return "间隙";
    case "before_open":
      return "盘前";
    case "after_close":
      return "盘后";
    case "weekend":
      return "周末";
    default:
      return s;
  }
}

export default IntradayCockpit;
