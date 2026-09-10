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
import { cn } from "@/lib/utils";
import { HonestyBanner } from "@/components/ui/HonestyBanner";
import type { FirstBoardCandidatesResponse } from "@/lib/api";
import { NODE, ArrowDown } from "@/components/pipeline/primitives";
// S179 R3.4: 拆分——节点组件抽到 first-board-pipeline/nodes.tsx
import {
  FilterPipelineNode,
  ConfirmNode,
  PositionNode,
  SellNode,
  SettlementNode,
  FeishuStatusBar,
} from "./first-board-pipeline/nodes";

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
