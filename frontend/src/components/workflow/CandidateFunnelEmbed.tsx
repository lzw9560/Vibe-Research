// S093 T11：从 PreMarketBriefing 私有函数抽为可复用组件（Oracle 阻断项 #4）。
// 保留原 props 签名 + SelectionPipeline import + 返 null 逻辑，供前瞻 Tab 复用。
// S073 SelectionPipeline 替换 FunnelMatrixSimple/ScoredCandidateTable 互斥：
// 同图显 R1/R2/R3 + scored（漂移徽标，不臆造串联 R3→scored）；activeStrategy 不再换候选宇宙

import { SelectionPipeline } from "@/components/pipeline/SelectionPipeline";
import type { FunnelLayer } from "@/lib/candidates";
import type { ScoredCandidate } from "@/lib/api";

interface CandidateFunnelEmbedProps {
  date?: string;
  onPick: (code: string) => void;
  snapshotLayers?: FunnelLayer[];
  scoredCandidates?: ScoredCandidate[];
  ztPoolSize?: number;
}

export default function CandidateFunnelEmbed({
  date,
  onPick,
  snapshotLayers,
  scoredCandidates,
  ztPoolSize,
}: CandidateFunnelEmbedProps) {
  if (
    (!snapshotLayers || snapshotLayers.length === 0) &&
    (!scoredCandidates || scoredCandidates.length === 0)
  ) {
    return null;
  }
  return (
    <SelectionPipeline
      funnelLayers={snapshotLayers}
      scoredCandidatesCount={scoredCandidates?.length}
      screenerPoolSize={ztPoolSize}
      mode="full"
      date={date}
      onPick={onPick}
      showHonestyBanner={false}
    />
  );
}
