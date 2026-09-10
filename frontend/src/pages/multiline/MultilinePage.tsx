// S179 Phase 2 R2.2: /multiline 三列战略页——短线打板 / 中线 event / 长线价值
// grill #7（§44v1 教训）：每列 verdict 须标窗口口径，防"某窗口无 edge → 整体无 edge"外推越界
// 长线列 honest placeholder（S171 R2 verdict harness 未跑，当前 mock）
// 对接：S168 selection verdict / S169+S170 event verdict / S171 long_value（待跑）
// 措辞原则（memory feedback-style-plain-chinese）：用人话直答，术语括号注一次不堆砌
import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { GlassCard } from "@/components/ui/GlassCard";
import { VerdictRenderer } from "@/components/verdict/VerdictRenderer";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { cn } from "@/lib/utils";

// ── 三列战略定义（不可变常量，非运行时状态）──────────────────────────────────
interface StrategyColumnDef {
  key: "short" | "mid" | "long";
  title: string;
  subtitle: string;
  windowLabel: string; // grill #7：窗口口径标签（§44v1 教训——同一因子不同窗口结论不同）
  windowNote: string; // 窗口口径注解（防外推越界）
  honestLabel: string; // 诚实标签（当前 verdict 状态）
  accent: string; // 列色调（色不单独承义，总配文字）
}

const COLUMNS: readonly StrategyColumnDef[] = [
  {
    key: "short",
    title: "短线打板",
    subtitle: "selection 层（S168）",
    windowLabel: "D+1 开盘 → D+4 path",
    // §44v1 教训：此窗口测 selection 全否，但隔夜 gap（真 edge）未折进——非"整体无 edge"
    windowNote:
      "§44v1 框架口径。此窗口测 selection 全否，但隔夜 gap（真 edge）未折进——非"整体无 edge"。",
    honestLabel:
      "S168 12 harness 全 falsified/exploratory — breakout 证否，打板 selection 无 validated edge，edge 待盘中验证",
    accent: "border-l-red-500/40",
  },
  {
    key: "mid",
    title: "中线 event",
    subtitle: "event 层（S169 + S170）",
    windowLabel: "隔夜 gap D收→D+1开 / 摘帽后中线 path",
    windowNote:
      "gap = robust_edge 60d（t=4.12）待复验 · 摘帽 underpowered",
    honestLabel:
      "S169 PEAD gap robust_edge 60d（t=4.12）待复验 · S170 摘帽 5 verdict underpowered",
    accent: "border-l-amber-500/40",
  },
  {
    key: "long",
    title: "长线价值",
    subtitle: "long_value 层（S171）",
    windowLabel: "月底调仓持 1 月",
    windowNote: "S171 spec done R3，R2 verdict harness 待跑",
    honestLabel: "verdict 待跑——S171 R2 long_value_run.py 未运行，当前 mock 数据",
    accent: "border-l-blue-500/40",
  },
];

export function MultilinePage() {
  return (
    <div className="space-y-4 p-4 max-w-7xl mx-auto">
      {/* ── 页头：标题 + 窗口口径说明 ── */}
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">多策略总览</h1>
        <p className="text-sm text-muted-foreground leading-relaxed">
          三列战略——短线打板 / 中线 event / 长线价值。每列标窗口口径（§44v1 教训：同一因子不同窗口结论不同，防"某窗口无 edge → 整体无 edge"外推）。
        </p>
      </header>

      {/* ── 三列 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        {COLUMNS.map((col) => (
          <StrategyColumn key={col.key} def={col} />
        ))}
      </div>
    </div>
  );
}

// ── 单列组件 ──────────────────────────────────────────────────────────────────

function StrategyColumn({ def }: { def: StrategyColumnDef }) {
  return (
    <GlassCard className={cn("p-4 space-y-3 border-l-2", def.accent)}>
      {/* 列头 */}
      <div>
        <h2 className="text-base font-semibold">{def.title}</h2>
        <p className="text-xs text-muted-foreground">{def.subtitle}</p>
      </div>

      {/* 窗口口径标签（grill #7：§44v1 教训） */}
      <div className="rounded bg-muted/30 px-2.5 py-1.5">
        <div className="text-[11px] text-muted-foreground/80">窗口口径</div>
        <div className="text-xs font-medium text-foreground mt-0.5">
          {def.windowLabel}
        </div>
        <div className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
          {def.windowNote}
        </div>
      </div>

      {/* verdict 内容（per-type 分发，spec A10.3） */}
      {renderColumnContent(def)}

      {/* 诚实标签 */}
      <div className="rounded bg-amber-500/5 px-2.5 py-1.5 border-l-2 border-amber-500/30">
        <span className="text-[11px] text-amber-400/80">诚实标注</span>
        <p className="text-xs text-muted-foreground leading-relaxed mt-0.5">
          {def.honestLabel}
        </p>
      </div>
    </GlassCard>
  );
}

// 穷举 switch（3 case 全覆盖，tsc 无 fallthrough 警告）
function renderColumnContent(def: StrategyColumnDef): ReactNode {
  switch (def.key) {
    case "short":
      return <VerdictRenderer filterType="selection" />;
    case "mid":
      return <VerdictRenderer filterType="event" />;
    case "long":
      // 长线列 honest placeholder：S171 R2 verdict harness 未跑
      // VerdictRenderer filterType="long_value" 会 delegate 到 S171ValueVerdict（全页 max-w-6xl，不适三列内嵌）
      // → 此列用 HonestEmptyState 占位 + 链接到 /value-verdict 独立页（spec A10.2）
      return <LongValuePlaceholder />;
  }
}

// ── 长线列占位 ────────────────────────────────────────────────────────────────

function LongValuePlaceholder() {
  return (
    <HonestEmptyState
      message="长线价值 verdict 待跑"
      hint={
        <>
          S171 spec 已定稿（R3 done），但 R2 verdict harness（
          <code className="text-[10px]">long_value_run.py</code>）尚未运行。当前{" "}
          <Link to="/value-verdict" className="text-blue-400 hover:underline">
            价值因子验证页
          </Link>{" "}
          显示 mock 数据。
        </>
      }
    />
  );
}
