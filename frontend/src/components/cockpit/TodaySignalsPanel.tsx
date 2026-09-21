// S218 #9: TodaySignalsPanel——当日可行动信号 + 手动交易回录。
// 复用 ValidatedEdgeCard pattern（GlassCard + Disclaimer + useSignalsStatus 一致 cap/regime）。
// 数据：GET /api/signals/daily（结构化三 bucket）+ POST /api/signals/manual-trade（回录真成交）。
// §44 诚实性：标"统计验证/非已实现收益/paper-only/照做有风险"（同 C1 daily report strings）。
import { useState } from "react";
import {
  Loader2,
  AlertTriangle,
  TrendingDown,
  CheckCircle2,
  X,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet } from "@/components/ui/Sheet";
import { DeliveryStatusCard } from "./DeliveryStatusCard";
import {
  useSignalsDaily,
  useRecordManualTrade,
  useSignalsManualTrades,
} from "@/lib/query/signals";
import type { SignalsDailySignal, ManualTradeResponse } from "@/lib/api/types";

// §44 诚实性 strings（spec C1 daily report 同源，禁改软）
const HONESTY_VALIDATED = "统计验证（非已实现收益）";
const HONESTY_PAPER = "paper-only 无券商";
const HONESTY_RISK = "照做有风险";

/** regime + cap → 人话标签 */
function regimeCapLabel(regime: string, cap: number): string {
  if (cap === 0.75) return `bull ×${cap}`;
  if (cap === 0.5) return `${regime || "unknown"} ×0.5 保守`;
  return `×${cap}`;
}

/** 单条信号行 + "记录成交" 按钮 */
function SignalRow({
  signal,
  date,
  exploratory,
  matchedTrade,
  onRecord,
}: {
  signal: SignalsDailySignal;
  date: string;
  exploratory?: boolean;
  matchedTrade?: ManualTradeResponse | null;
  onRecord: (s: SignalsDailySignal) => void;
}) {
  const price = signal.entry_price;
  const priceStr =
    price !== null && price > 0 ? `¥${price.toFixed(2)}` : "N/A";
  return (
    <div className="flex items-center justify-between rounded border border-border/40 px-3 py-2 text-sm">
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono font-semibold">{signal.code}</span>
          <span className="truncate text-muted-foreground">{signal.name}</span>
          <span className="rounded bg-muted/40 px-1.5 py-0.5 text-xs">
            连板{signal.lbc}
          </span>
          {exploratory && (
            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
              探索性
            </span>
          )}
          {/* S221 gap3: delivery leak 标记——按 code 匹配 manual trade */}
          {matchedTrade && matchedTrade.pnl_diff?.delivery_leak && (
            <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-600">
              leak
            </span>
          )}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          参考价 {priceStr}
          {signal.price_source &&
            signal.price_source !== "N/A" &&
            signal.price_source !== date && (
              <span className="ml-1 text-muted-foreground">
                （来源 {signal.price_source}）
              </span>
            )}
          {/* S221 gap3: actual vs reference P&L diff（有 matchedTrade 才显示，诚实不臆造） */}
          {matchedTrade && matchedTrade.actual_pnl?.pnl_pct != null && (
            <span className="ml-2">
              实际{" "}
              <span className={matchedTrade.actual_pnl.pnl_pct >= 0 ? "text-emerald-600" : "text-red-500"}>
                {matchedTrade.actual_pnl.pnl_pct >= 0 ? "+" : ""}
                {matchedTrade.actual_pnl.pnl_pct.toFixed(2)}%
              </span>
              {matchedTrade.reference_pnl?.pnl_pct != null && (
                <span className="text-muted-foreground">
                  {" "}vs 参考 {matchedTrade.reference_pnl.pnl_pct.toFixed(2)}%
                </span>
              )}
            </span>
          )}
        </div>
      </div>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => onRecord(signal)}
        disabled={signal.unbuyable}
        title={signal.unbuyable ? "一字板不可买" : "记录实际成交"}
      >
        记录成交
      </Button>
    </div>
  );
}

/** 手动交易回录表单（Sheet 内）——预填 code/reference_signal_id/followed_reference */
function ManualTradeForm({
  signal,
  date,
  onClose,
}: {
  signal: SignalsDailySignal;
  date: string;
  onClose: () => void;
}) {
  const mutation = useRecordManualTrade();
  // 预填买入时间默认今日开盘附近（09:30），用户可改
  const defaultEntryTime = `${date}T09:30`;
  // entry_price 初始预填参考价（mount 时一次，ManualTradeForm key=code+date 每次
  // 打开新信号 remount）——不用 useEffect，避免用户清空后被立即回填
  const initialPrice =
    signal.entry_price && signal.entry_price > 0
      ? String(signal.entry_price)
      : "";
  const [entryPrice, setEntryPrice] = useState(initialPrice);
  const [entryTime, setEntryTime] = useState(defaultEntryTime);
  const [exitPrice, setExitPrice] = useState("");
  const [exitTime, setExitTime] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    const ep = parseFloat(entryPrice);
    if (!Number.isFinite(ep) || ep <= 0) {
      setError("实际买入价须 > 0");
      return;
    }
    if (!entryTime) {
      setError("买入时间必填");
      return;
    }
    const xp = exitPrice ? parseFloat(exitPrice) : null;
    if (xp !== null && (!Number.isFinite(xp) || xp <= 0)) {
      setError("卖出价须 > 0 或留空（未平仓）");
      return;
    }
    // reference_signal_id best-effort（匹配 consecutive_relay_{date}_{code} 格式；
    // 后端查不到 → ref_source=not_found，诚实不臆造）
    const referenceSignalId = `consecutive_relay_${date}_${signal.code}`;
    mutation.mutate(
      {
        code: signal.code,
        entry_price: ep,
        entry_time: entryTime,
        exit_price: xp,
        exit_time: xp !== null && exitTime ? exitTime : null,
        followed_reference: true,
        reference_signal_id: referenceSignalId,
        notes,
      },
      {
        onError: (e) => setError(e.message || "提交失败"),
      },
    );
  };

  const result = mutation.data;
  const submitting = mutation.isPending;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">记录实际成交</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground"
          aria-label="关闭"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* 信号摘要（预填只读） */}
      <div className="rounded bg-muted/30 px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold">{signal.code}</span>
          <span className="text-muted-foreground">{signal.name}</span>
          <span className="rounded bg-muted/40 px-1.5 py-0.5">
            连板{signal.lbc}
          </span>
        </div>
        <p className="mt-1 text-muted-foreground">
          参考价 {signal.entry_price ? `¥${signal.entry_price.toFixed(2)}` : "N/A"} ·
          关联信号 consecutive_relay_{date}_{signal.code}
        </p>
      </div>

      {/* 用户填：实际买入价 + 买入时间 */}
      <Input
        label="实际买入价 ¥"
        type="number"
        step="0.01"
        value={entryPrice}
        onChange={(e) => setEntryPrice(e.target.value)}
        placeholder="如 10.50"
        error={error && !entryPrice ? error : undefined}
      />
      <Input
        label="买入时间"
        type="datetime-local"
        value={entryTime}
        onChange={(e) => setEntryTime(e.target.value)}
        error={error && !entryTime ? error : undefined}
      />

      {/* 可选：卖出（已平仓才填） */}
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">
          已平仓？填卖出（可选）
        </summary>
        <div className="mt-2 space-y-2">
          <Input
            label="实际卖出价 ¥"
            type="number"
            step="0.01"
            value={exitPrice}
            onChange={(e) => setExitPrice(e.target.value)}
            placeholder="留空=未平仓"
          />
          <Input
            label="卖出时间"
            type="datetime-local"
            value={exitTime}
            onChange={(e) => setExitTime(e.target.value)}
            placeholder="留空=未平仓"
          />
        </div>
      </details>

      <Input
        label="备注（可选）"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="如 100 股 / 实盘 / 模拟"
      />

      {/* error */}
      {error && (
        <p className="text-xs text-red-500" data-testid="manual-trade-error">
          {error}
        </p>
      )}

      {/* result */}
      {result && (
        <div
          className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800"
          data-testid="manual-trade-result"
        >
          <div className="flex items-center gap-1 font-semibold">
            <CheckCircle2 className="h-3.5 w-3.5" /> 已记录 {result.trade_id}
          </div>
          <p className="mt-1">
            实际 P&L：{result.actual_pnl.pnl_pct ?? "未平仓"}%
            {result.actual_pnl.status === "open" && "（持仓中）"}
          </p>
          {result.reference_pnl.pnl_pct !== null && (
            <p className="text-muted-foreground">
              参考 P&L：{result.reference_pnl.pnl_pct}%（{result.reference_pnl.source}）
            </p>
          )}
          {result.delivery_leak && (
            <p className="mt-1 text-red-600">
              ⚠️ delivery_leak：实际 vs 参考差异过大（{result.pnl_diff.leak_reason}）
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Button onClick={submit} disabled={submitting}>
          {submitting ? "提交中..." : "提交成交记录"}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          关闭
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {HONESTY_PAPER}——记录的是你的真成交，不自动下单。
      </p>
    </div>
  );
}

export function TodaySignalsPanel() {
  const { data, isLoading, isError } = useSignalsDaily();
  const { data: tradesResp } = useSignalsManualTrades();
  const [sheetSignal, setSheetSignal] = useState<SignalsDailySignal | null>(
    null,
  );

  const date = data?.date ?? "";
  const regime = data?.regime?.current ?? "unknown";
  const cap = data?.cap?.effective ?? 1.0;
  const hardstop = data?.hardstop;
  const filters = data?.filters;
  const verified = data?.verified_numbers;
  const disclaimers = data?.disclaimers ?? [];

  // S221 gap3: 按 code 建 manual trade Map，传 SignalRow 显示 diff/leak
  const tradeByCode = new Map<string, ManualTradeResponse>();
  for (const t of tradesResp?.trades ?? []) {
    // 同 code 取最新一条（倒序已按时间）
    if (!tradeByCode.has(t.code)) tradeByCode.set(t.code, t);
  }

  const tradable = (data?.signals ?? []).filter((s) => s.bucket === "tradable");
  const exploratory = (data?.signals ?? []).filter(
    (s) => s.bucket === "exploratory",
  );
  const avoid = (data?.signals ?? []).filter((s) => s.bucket === "avoid");

  return (
    <GlassCard className="p-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">今日信号（可行动参考）</h3>
        <span className="text-xs text-muted-foreground">consecutive_relay</span>
      </div>

      {/* S221 gap1: 推送状态灯（cron fire + 飞书配置态） */}
      <DeliveryStatusCard />

      {/* Honesty banner（§44 诚实性 gate，同 C1） */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">
          {HONESTY_VALIDATED}
        </span>
        <span className="rounded bg-muted/30 px-1.5 py-0.5">
          {HONESTY_PAPER}
        </span>
        <span className="rounded bg-red-50 px-1.5 py-0.5 text-red-600">
          {HONESTY_RISK}
        </span>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
          <Loader2 className="animate-spin mr-2 h-4 w-4" />
          加载今日信号...
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="h-[120px] flex items-center justify-center text-red-500 text-sm">
          今日信号加载失败
        </div>
      )}

      {/* Content */}
      {!isLoading && !isError && data && (
        <>
          {/* 状态行：date + regime + cap + hardstop */}
          <div className="mb-3 rounded border border-border/40 px-3 py-2 text-xs">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono font-semibold">{date || "—"}</span>
              <span className="text-muted-foreground">·</span>
              <span>{regimeCapLabel(regime, cap)}</span>
              {hardstop?.active && (
                <span className="inline-flex items-center gap-1 rounded bg-red-50 px-1.5 py-0.5 text-red-600">
                  <AlertTriangle className="h-3 w-3" /> hard-stop
                </span>
              )}
            </div>
            {data.regime.edge_status && (
              <p className="mt-1 text-muted-foreground">
                {data.regime.edge_status}
              </p>
            )}
            {hardstop?.active && hardstop.reason && (
              <p className="mt-1 text-red-600">{hardstop.reason}</p>
            )}
            {/* filters 诚实计数 */}
            {filters && (
              <p className="mt-1 text-muted-foreground">
                扫描 {filters.total_scanned} 只 → {filters.tradable} 可做 /{" "}
                {filters.exploratory} 探索性 / {filters.avoid} 别碰
              </p>
            )}
          </div>

          {/* hard-stop 触发时全标探索性提示 */}
          {hardstop?.active && (
            <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              <AlertTriangle className="mr-1 inline h-3 w-3" />
              hard-stop 触发：所有信号归"探索性"，0 tradable。{hardstop.reason}
            </div>
          )}

          {/* Tradable picks（bull ×0.75 validated edge） */}
          <div className="mb-3">
            <div className="mb-1.5 flex items-center gap-1.5">
              <TrendingDown className="h-3.5 w-3.5 text-amber-600" />
              <h4 className="text-xs font-semibold">
                可做（{tradable.length} 只）— bull validated
              </h4>
            </div>
            {tradable.length === 0 ? (
              <p className="rounded border border-border/40 px-3 py-2 text-xs text-muted-foreground">
                无可做信号
              </p>
            ) : (
              <div className="space-y-1.5">
                {tradable.map((s) => (
                  <SignalRow
                    key={s.code}
                    signal={s}
                    date={date}
                    matchedTrade={tradeByCode.get(s.code)}
                    onRecord={setSheetSignal}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Exploratory picks（bear/range ×0.5 保守） */}
          <div className="mb-3">
            <div className="mb-1.5 flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
              <h4 className="text-xs font-semibold">
                探索性（{exploratory.length} 只）— ×0.5 underpowered
              </h4>
            </div>
            {exploratory.length === 0 ? (
              <p className="rounded border border-border/40 px-3 py-2 text-xs text-muted-foreground">
                无探索性信号
              </p>
            ) : (
              <div className="space-y-1.5">
                {exploratory.map((s) => (
                  <SignalRow
                    key={s.code}
                    signal={s}
                    date={date}
                    exploratory
                    matchedTrade={tradeByCode.get(s.code)}
                    onRecord={setSheetSignal}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Avoid picks（一字板不可买 + 数据缺失） */}
          {avoid.length > 0 && (
            <div className="mb-3">
              <h4 className="mb-1.5 text-xs font-semibold text-muted-foreground">
                别碰（{avoid.length} 只）— 一字板不可买 / 数据缺失
              </h4>
              <div className="space-y-1.5">
                {avoid.map((s) => (
                  <div
                    key={s.code}
                    className="flex items-center justify-between rounded border border-border/40 px-3 py-2 text-sm text-muted-foreground"
                  >
                    <div>
                      <span className="font-mono">{s.code}</span>{" "}
                      <span>{s.name}</span>{" "}
                      <span className="text-xs">连板{s.lbc}</span>
                    </div>
                    <span className="text-xs">{s.missing_bar ? "数据缺失" : "一字板"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 验证数字（§44 chrono + deep_dive） */}
          {verified && (
            <div className="mb-3 grid grid-cols-4 gap-2">
              <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
                <p className="text-xs text-muted-foreground">train</p>
                <p className="text-sm font-bold text-amber-600">
                  {verified.chrono_train}%
                </p>
              </div>
              <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
                <p className="text-xs text-muted-foreground">test</p>
                <p className="text-sm font-bold text-amber-600">
                  {verified.chrono_test}%
                </p>
              </div>
              <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
                <p className="text-xs text-muted-foreground">衰减</p>
                <p className="text-sm font-bold text-red-500">
                  -{verified.chrono_decay_pct}%
                </p>
              </div>
              <div className="rounded bg-muted/30 px-2 py-1.5 text-center">
                <p className="text-xs text-muted-foreground">WR</p>
                <p className="text-sm font-bold">{verified.chrono_wr}%</p>
              </div>
            </div>
          )}

          {/* 入场指引 */}
          <div className="mb-3 rounded border border-border/40 px-3 py-2 text-xs text-muted-foreground">
            <strong className="text-foreground">入场指引：</strong>
            今日 14:57-15:00 收盘集合竞价市价买，参考价 = 最近可得收盘价，实际成交价 ≈
            参考价 ± 小范围波动。
          </div>

          {/* 免责声明（spec §44 reframe 版，后端 disclaimers） */}
          {disclaimers.length > 0 && (
            <ul className="mb-3 space-y-1 text-xs text-muted-foreground">
              {disclaimers.map((d, i) => (
                <li key={i} className="leading-relaxed">
                  · {d}
                </li>
              ))}
            </ul>
          )}

          <Disclaimer compact />
        </>
      )}

      {/* 手动交易回录 Sheet */}
      <Sheet
        open={sheetSignal !== null}
        onClose={() => setSheetSignal(null)}
      >
        {sheetSignal && (
          <ManualTradeForm
            // key by code+date → 每次打开新信号表单 reset
            key={`${sheetSignal.code}_${date}`}
            signal={sheetSignal}
            date={date}
            onClose={() => setSheetSignal(null)}
          />
        )}
      </Sheet>
    </GlassCard>
  );
}
