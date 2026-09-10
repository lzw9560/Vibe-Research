// S178: OFI 盘中数据只读看板页（薄包装，仿 Journal 页包装 JournalLedger）。
import { OfiDashboard } from "@/components/intraday/OfiDashboard";

export default function OfiDashboardPage() {
  return (
    <div className="mx-auto max-w-5xl p-4">
      <h2 className="mb-3 font-serif text-lg font-bold">OFI 盘中数据看板</h2>
      <OfiDashboard />
    </div>
  );
}
