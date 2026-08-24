// S093 T11：从 PreMarketBriefing 私有函数抽为可复用组件（Oracle 阻断项 #4）。
// 保留原 props 签名 + SelectionPipeline import + 返 null 逻辑，供前瞻 Tab 复用。
// S073 SelectionPipeline 替换 FunnelMatrixSimple/ScoredCandidateTable 互斥：
// 同图显 R1/R2/R3 + scored（漂移徽标，不臆造串联 R3→scored）；activeStrategy 不再换候选宇宙

import { SelectionPipeline } from "@/components/pipeline/SelectionPipeline";
import type { FunnelLayer, DiagnosisCard } from "@/lib/candidates";
import type { ScoredCandidate } from "@/lib/api";

interface CandidateFunnelEmbedProps {
  date?: string;
  onPick: (code: string) => void;
  snapshotLayers?: FunnelLayer[];
  scoredCandidates?: ScoredCandidate[];
  /** S094 T17/R28：briefing 透传的 market_scan_scored（非涨停 pipeline）。 */
  marketScanScored?: ScoredCandidate[];
  /** S094 T25：briefing 透传的 final_candidates（定稿节点，R25 定稿失配修复）。 */
  finalCandidates?: DiagnosisCard[];
  ztPoolSize?: number;
  /** S094 附录 A2：板块轮动由前置共享区统一渲染时传 true（默认）——SelectionPipeline 内部不再渲染。 */
  sharedSectorRotation?: boolean;
}

export default function CandidateFunnelEmbed({
  date,
  onPick,
  snapshotLayers,
  scoredCandidates,
  marketScanScored,
  finalCandidates,
  ztPoolSize,
  sharedSectorRotation = true,
}: CandidateFunnelEmbedProps) {
  if (
    (!snapshotLayers || snapshotLayers.length === 0) &&
    (!scoredCandidates || scoredCandidates.length === 0) &&
    (!marketScanScored || marketScanScored.length === 0) &&
    (!finalCandidates || finalCandidates.length === 0) &&
    !ztPoolSize  // S094 audit LOW: zt_count>0 时显涨停股池根节点,四数组空不藏
  ) {
    return null;
  }
  return (
    <SelectionPipeline
      funnelLayers={snapshotLayers}
      scoredCandidatesCount={scoredCandidates?.length}
      screenerPoolSize={ztPoolSize}
      nonLimitupCandidates={marketScanScored}
      finalCandidates={finalCandidates}
      mode="full"
      date={date}
      onPick={onPick}
      showHonestyBanner={false}
      sharedSectorRotation={sharedSectorRotation}
    />
  );
}
