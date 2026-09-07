// S166: 交易日志 + 风险账本页（Trade Journal + Risk Ledger，fresh-impl）。
// 4 tab：交易日志 / 风险账本 / 诊断 / 设置。每 tab 各自 load 数据，独立错误处理。
// 不臆造：后端未就绪各 section 显 ApiError 横幅；空数据/available:False 如实呈现 reason。
import { useState } from "react";
import { TradeJournalSection } from "@/components/journal/TradeJournalSection";
import { RiskReportSection } from "@/components/journal/RiskReportSection";
import { DiagnosticsSection } from "@/components/journal/DiagnosticsSection";
import { JournalSettings } from "@/components/journal/JournalSettings";

type Tab = "trades" | "risk" | "diag" | "settings";

const TABS: { key: Tab; label: string }[] = [
  { key: "trades", label: "交易日志" },
  { key: "risk", label: "风险账本" },
  { key: "diag", label: "诊断" },
  { key: "settings", label: "设置" },
];

export function Journal() {
  const [tab, setTab] = useState<Tab>("trades");
  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">交易日志 + 风险账本</h1>
        <span className="text-[10px] text-muted-foreground">S166 fresh-impl · 个人数据不接 AI prompt</span>
      </div>
      <div className="flex flex-wrap gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`border-b-2 px-3 py-1.5 text-sm transition-colors ${
              tab === t.key
                ? "border-blue-500 text-blue-500"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div>
        {tab === "trades" && <TradeJournalSection />}
        {tab === "risk" && <RiskReportSection />}
        {tab === "diag" && <DiagnosticsSection />}
        {tab === "settings" && <JournalSettings />}
      </div>
    </div>
  );
}
