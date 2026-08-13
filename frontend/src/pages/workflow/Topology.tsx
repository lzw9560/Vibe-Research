// S024-E1 拓扑视图入口：页内 TabBar 切换三视图（关系网/漏斗流程/连板梯队）。
// 复用 S023 详情路由（RelationGraph 节点点击）+ S023 funnel/layers（FunnelFlow）+ em_zt_topic_pool（BoardLadder）。
// 复用 ui 组件（PageHeader/TabBar）。仿 AuctionScreener TabBar 范式。
// 合规 §0（弱合规·工程底线）：拓扑入口只呈现客观关联，不输出方向词。
import { useState } from "react";
import { Share2, Filter, Layers } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabBar } from "@/components/ui/TabBar";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { RelationGraph } from "@/components/topology/RelationGraph";
import { FunnelFlow } from "@/components/topology/FunnelFlow";
import { BoardLadder } from "@/components/topology/BoardLadder";
import { useTopologyRelation, useFunnelLayers, useBoardLadder } from "@/lib/query";

/** 页内 Tab key：relation=关系网，funnel=漏斗流程，ladder=连板梯队。 */
type TopologyTab = "relation" | "funnel" | "ladder";

const TABS: { key: TopologyTab; label: string; icon: React.ReactNode }[] = [
  { key: "relation", label: "关系网", icon: <Share2 className="h-4 w-4" aria-hidden="true" /> },
  { key: "funnel", label: "漏斗流程", icon: <Filter className="h-4 w-4" aria-hidden="true" /> },
  { key: "ladder", label: "连板梯队", icon: <Layers className="h-4 w-4" aria-hidden="true" /> },
];

/** 连板梯队树叶子计数（递归） */
function countLadderLeaves(node?: { children?: unknown[] } | null): number {
  if (!node) return 0;
  const children = node.children as { children?: unknown[] }[] | undefined;
  if (!children || children.length === 0) return 1;
  return children.reduce((sum, c) => sum + countLadderLeaves(c as { children?: unknown[] }), 0);
}

/** 梯队分层数据（第一层 children 各节点 + 叶子数） */
function ladderLayers(node: { children?: { name: string; children?: unknown[] }[] } | null | undefined): string {
  if (!node || !node.children || node.children.length === 0) return "无";
  return node.children.map((c) => `${c.name}×${countLadderLeaves(c)}`).join("，");
}

interface TopologyProps {
  /** ISO 日期；默认今日（后端处理）。三视图共享同一日期维度。 */
  date?: string;
}

/**
 * 拓扑展示页：三视图可切换，共用图引擎（GraphView）。
 * - 关系网（RelationGraph）：候选标的四类客观关联边（sector/fund_flow/ladder/seat），节点点击进详情
 * - 漏斗流程（FunnelFlow）：漏斗层 R1→R2→R3→自选 数据流向，点节点展开通过候选
 * - 连板梯队（BoardLadder）：em_zt_topic_pool 涨停池按高度分层，叶节点呈现 code/name
 *
 * 三视图各自封装数据接线 + 三态（loading/error/empty），本页只做 Tab 切换容器。
 * 拓扑只呈现客观关联，不输出方向结论（§0 弱合规·工程底线）。
 */
export function Topology({ date }: TopologyProps) {
  const [activeTab, setActiveTab] = useState<TopologyTab>("relation");

  // 问 AI 上下文——复用子组件同 hook（TanStack Query 缓存命中零成本）
  const relationQ = useTopologyRelation(date);
  const funnelQ = useFunnelLayers(date);
  const ladderQ = useBoardLadder(date);
  const edgeTypes = relationQ.data ? [...new Set(relationQ.data.edges.map((e) => e.type))] : [];
  const askAiContext = [
    `当前页面：拓扑展示`,
    `当前视图：${TABS.find((t) => t.key === activeTab)?.label ?? activeTab}`,
    relationQ.data
      ? `关系网：${relationQ.data.nodes.length}节点/${relationQ.data.edges.length}边（关联类型：${edgeTypes.join("、") || "无"}）`
      : `关系网：未取得`,
    funnelQ.data && funnelQ.data.length > 0
      ? `漏斗流向：${funnelQ.data.map((l) => `${l.layer_id}输出${l.output_count}`).join("→")}`
      : `漏斗流向：未取得`,
    ladderQ.data
      ? `连板梯队：${ladderLayers(ladderQ.data)}`
      : `连板梯队：未取得`,
  ].join("\n");

  return (
    <div className="space-y-4">
      <PageHeader
        title="拓扑展示"
        subtitle="关系网 · 漏斗流程 · 连板梯队 三视角客观关联（只呈现，不附方向结论）"
        actions={<AskAiButton context={askAiContext} />}
      />

      <TabBar
        tabs={TABS}
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as TopologyTab)}
      />

      {activeTab === "relation" && <RelationGraph date={date} />}
      {activeTab === "funnel" && <FunnelFlow date={date} />}
      {activeTab === "ladder" && <BoardLadder date={date} />}

      <Disclaimer compact />
    </div>
  );
}
