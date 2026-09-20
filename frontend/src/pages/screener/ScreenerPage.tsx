// S179 Phase 1: 通用选股器主页——搜索框 + filter 框架 + preset 入口 + 结果列表 + 送入菜单。
// grill #5 决策：不强行统一 limitup 5 子页 UI（gene/auction/seats 独特交互），
//              preset 保留入口跳现有 /limitup/* 路由。
// grill #12：统一筛选 API vs 前端 fan-out 待定——filter 结果后端未接线，
//            当前 UI 框架 + preset 跳转 + 搜索 + 送入菜单可用。
import { useState, useCallback, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Search, RotateCcw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { SendToMenu, type SendPayload } from "@/components/common/SendToMenu";
import { useSelectStock } from "@/stores/currentStock";
import { FilterPanel, type ScreenerFilters, DEFAULT_FILTERS } from "./FilterPanel";
import { SCREENER_PRESETS } from "./presets";

/** 筛选结果行（API 接线后从后端返回，grill #12 待定） */
export interface ScreenerRow {
  code: string;
  name: string;
  industry: string;
  marketCap: number; // 亿元
  pe: number | null;
  pb: number | null;
  roe: number | null; // %
  changePct: number; // %
}

/** A股涨跌色：红涨绿跌 */
function pctColor(pct: number): string {
  if (pct > 0) return "text-[hsl(0_74%_60%)]";
  if (pct < 0) return "text-[hsl(145_62%_47%)]";
  return "text-muted-foreground";
}

const SEND_LABELS: Record<SendPayload["target"], string> = {
  watchlist: "自选",
  portfolio: "持仓",
  journal: "交易日志",
  research: "研究记录",
};

export function ScreenerPage() {
  const [filters, setFilters] = useState<ScreenerFilters>(DEFAULT_FILTERS);
  const [searchQuery, setSearchQuery] = useState("");
  const [sentMsg, setSentMsg] = useState<string | null>(null);
  const selectStock = useSelectStock();
  const navigate = useNavigate();

  // 结果列表（grill #12：筛选 API 待接入，当前空数组，API 接线后替换为 query hook）
  const rows: ScreenerRow[] = [];

  // preset 跳现有 /limitup/* 路由（非重建，grill #5）
  const handlePresetNavigate = useCallback(
    (path: string) => {
      navigate(path);
    },
    [navigate],
  );

  // filter 重置
  const handleReset = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
  }, []);

  // 行点击 → selectStock + 跳个股页（Bloomberg Linking）
  const handleRowSelect = useCallback(
    (code: string, name: string) => {
      selectStock(code, name, "screener");
      navigate(`/stock/${code}`);
    },
    [selectStock, navigate],
  );

  // 搜索框回车 → 跳个股页
  const handleSearchSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const q = searchQuery.trim();
      if (!q) return;
      selectStock(q, undefined, "screener");
      navigate(`/stock/${q}`);
    },
    [searchQuery, selectStock, navigate],
  );

  // 送入菜单回调——后端接线 P1 阶段（SendToMenu spec §9 grill #14）
  // watchlist POST 待建 / portfolio 待核实 / journal 需适配 signal_id / research=localStorage
  const handleSend = useCallback((payload: SendPayload) => {
    const label = SEND_LABELS[payload.target];
    setSentMsg(`已送入「${label}」(${payload.code} ${payload.name})——后端接线 P1`);
    setTimeout(() => setSentMsg(null), 3000);
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader
        title="选股器"
        subtitle="通用筛选框架 + 打板 preset 入口（preset 跳现有子页，非重建）"
      />

      {/* honest banner：grill #12 筛选 API 待定 */}
      <GlassCard className="p-3">
        <div className="text-[12px] text-muted-foreground">
          通用筛选 API 待接入（grill #12：统一筛选 API vs 前端 fan-out 待定）。当前 preset 入口跳转 + 搜索可用。
        </div>
      </GlassCard>

      {/* 顶部搜索框（回车跳个股页） */}
      <GlassCard className="p-3">
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="输入股票代码或名称（回车跳个股页）"
            className="flex-1 rounded border border-border bg-background px-3 py-1.5 text-sm outline-none focus:border-primary/50"
          />
        </form>
      </GlassCard>

      {/* preset 入口（5 按钮 → 跳现有 /limitup/* 路由） */}
      <GlassCard className="p-3">
        <div className="mb-2 text-[12px] text-muted-foreground">
          打板 preset（跳现有子页）
        </div>
        <div className="flex flex-wrap gap-2">
          {SCREENER_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => handlePresetNavigate(p.path)}
              title={p.description}
              className="rounded-lg border border-border/60 bg-card/30 px-3 py-1.5 text-[13px] text-foreground transition-colors hover:border-primary/40 hover:text-primary"
            >
              {p.name}
            </button>
          ))}
        </div>
      </GlassCard>

      {/* 筛选面板（6 条件组 + preset 下拉） */}
      <FilterPanel
        filters={filters}
        onChange={setFilters}
        onReset={handleReset}
        onPresetSelect={handlePresetNavigate}
      />

      {/* 送入反馈（SendToMenu onSend → 临时提示，后端接线 P1） */}
      {sentMsg && (
        <div className="rounded-md bg-primary/10 px-3 py-2 text-[12px] text-primary">
          {sentMsg}
        </div>
      )}

      {/* 结果列表（API 接线后填充，当前空数组 → honest 空态） */}
      <GlassCard>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">筛选结果</h3>
          <span className="text-xs text-muted-foreground">{rows.length} 条</span>
        </div>

        {rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-1 pr-2">代码</th>
                  <th className="py-1 pr-2">名称</th>
                  <th className="py-1 pr-2">行业</th>
                  <th className="py-1 pr-2">市值(亿)</th>
                  <th className="py-1 pr-2">PE</th>
                  <th className="py-1 pr-2">PB</th>
                  <th className="py-1 pr-2">ROE%</th>
                  <th className="py-1 pr-2">涨幅%</th>
                  <th className="py-1 pr-2">送入</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.code}
                    onClick={() => handleRowSelect(row.code, row.name)}
                    className="cursor-pointer border-b border-border/50 transition-colors hover:bg-muted/20"
                  >
                    <td className="py-1 pr-2 font-mono">{row.code}</td>
                    <td className="py-1 pr-2 font-medium">{row.name}</td>
                    <td className="py-1 pr-2 text-muted-foreground">{row.industry}</td>
                    <td className="py-1 pr-2 font-mono">{row.marketCap.toFixed(1)}</td>
                    <td className="py-1 pr-2 font-mono">{row.pe?.toFixed(1) ?? "—"}</td>
                    <td className="py-1 pr-2 font-mono">{row.pb?.toFixed(2) ?? "—"}</td>
                    <td className="py-1 pr-2 font-mono">{row.roe?.toFixed(1) ?? "—"}</td>
                    <td className={`py-1 pr-2 font-mono ${pctColor(row.changePct)}`}>
                      {row.changePct >= 0 ? "+" : ""}
                      {row.changePct.toFixed(2)}
                    </td>
                    {/* stopPropagation 防送入按钮触发行点击 */}
                    <td className="py-1 pr-2" onClick={(e) => e.stopPropagation()}>
                      <SendToMenu
                        code={row.code}
                        name={row.name}
                        sourcePage="screener"
                        onSend={handleSend}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center">
            <div className="text-sm text-muted-foreground">通用筛选结果待接入</div>
            <div className="mt-1 text-[12px] text-muted-foreground">
              后端筛选 API 建成后，按上方条件筛选全市场股票并展示在此
            </div>
            <button
              type="button"
              onClick={handleReset}
              className="mt-3 inline-flex items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
            >
              <RotateCcw className="h-3 w-3" />
              重置条件
            </button>
          </div>
        )}
      </GlassCard>
    </div>
  );
}

export default ScreenerPage;
