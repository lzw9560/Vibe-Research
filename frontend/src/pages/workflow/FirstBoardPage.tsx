// S075 067+075：首板流页面——选股工作流首个实现战法页面。
// 复用 WorkflowStage 壳（title="首板流" subtitle="首板涨停股 T+1 操作工作流"）。
// 两个 tab：①Pipeline 主视图 ②战法归因深看
// 顶部标注 §44 未 validated 仅参考（HonestyBanner 在 Pipeline 内 + tab 切换 + page 顶部脚注）。
//
// 数据来源：useFirstBoardCandidates（GET /api/workflow/first-board/candidates?date=）
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { WorkflowStage } from "./components/WorkflowStage";
import { FirstBoardPipeline } from "./components/FirstBoardPipeline";
import { StrategyAttributionTab } from "./components/StrategyAttributionTab";
import { useFirstBoardCandidates } from "@/lib/query";

type Tab = "pipeline" | "strategy-attribution";

export default function FirstBoardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedDate = searchParams.get("date") ?? undefined;
  const [tab, setTab] = useState<Tab>("pipeline");

  const { data, isLoading, error, refetch, isFetching } = useFirstBoardCandidates(selectedDate);
  const refreshing = isFetching && !isLoading;

  const handleRefresh = () => refetch();

  const handleDateChange = (value: string) => {
    if (!value) return;
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("date", value);
      return next;
    });
  };
  const clearDate = () => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("date");
      return next;
    });
  };

  // 问 AI 上下文
  const askAiContext = useMemo(() => {
    return [
      `当前页面：首板流（Pipeline 主视图${tab === "strategy-attribution" ? "·战法归因" : ""}）`,
      `数据日期：${data?.date ?? "未取得"}`,
      data
        ? `涨停池 ${data.zt_pool_count} / 首板 ${data.first_board_count} / 候选 ${data.candidates.length} / 剔除 ${data.excluded.length}`
        : `首板流数据：未取得`,
      data?.env_flags
        ? `大盘跌 ${data.env_flags.market_drop_pct ?? "—"}% / 高风险 ${data.env_flags.high_risk} / 最高板 ${data.env_flags.max_boards ?? "—"} / 梯队断裂 ${data.env_flags.ladder_broken}`
        : `市场环境：未取得`,
      data?.note ?? "",
      tab === "strategy-attribution"
        ? `战法归因：同股多战法命中不排除（§44 未 validated 仅复盘参考）`
        : `Pipeline：5 步闭环（筛选→确认→建仓→卖出→结算）`,
    ].filter(Boolean).join("\n");
  }, [data, tab]);

  // §44 诚实标注（page 顶部）
  const section44Note = "§44 未 validated 仅参考 · 9 维度评分权重待回测校准（30 天后用实际数据调）";

  return (
    <WorkflowStage
      title="首板流"
      subtitle="首板涨停股 T+1 操作工作流"
      loading={isLoading && !data}
      onRefresh={handleRefresh}
      actions={
        <>
          <AskAiButton context={askAiContext} />
          <input
            type="date"
            value={selectedDate ?? ""}
            onChange={(e) => handleDateChange(e.target.value)}
            aria-label="选择历史日期"
            className="rounded-lg border border-border/40 bg-muted/10 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          {selectedDate && (
            <button
              type="button"
              onClick={clearDate}
              className="text-xs text-muted-foreground hover:text-primary"
            >
              回到今日
            </button>
          )}
        </>
      }
    >
      {/* §44 诚实标注（页面顶部） */}
      <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200/80">
        ⚠ {section44Note}
      </div>

      {/* 错误态 */}
      {error && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          首板流数据取得失败：{error instanceof Error ? error.message : "未知错误"}
          <button
            type="button"
            onClick={handleRefresh}
            className="ml-2 text-xs underline hover:no-underline"
          >
            重试
          </button>
        </div>
      )}

      {/* 刷新提示 */}
      {refreshing && (
        <div className="mb-3 text-xs text-muted-foreground/60">刷新中…</div>
      )}

      {/* Tab 切换 */}
      <div className="mb-4 flex items-center gap-1 border-b border-border/40">
        <TabButton active={tab === "pipeline"} onClick={() => setTab("pipeline")}>
          ① Pipeline 主视图
        </TabButton>
        <TabButton active={tab === "strategy-attribution"} onClick={() => setTab("strategy-attribution")}>
          ② 战法归因深看
        </TabButton>
      </div>

      {/* Tab 内容 */}
      {tab === "pipeline" ? (
        <FirstBoardPipeline data={data ?? null} isLoading={isLoading && !data} />
      ) : (
        <StrategyAttributionTab data={data ?? null} />
      )}

      <Disclaimer compact />
    </WorkflowStage>
  );
}

// ---- Tab 按钮（轻量本地实现，避免新增 import）----
function TabButton({
  active, onClick, children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "border-b-2 px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
