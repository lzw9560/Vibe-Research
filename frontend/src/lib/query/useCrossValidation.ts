// S093 T12 + S146：交叉验证——涨停叉内 final_candidates(漏斗终选) ∩ scored_candidates(战法命中)。
// 前瞻④交叉验证 + 当日 WatchlistBoard 复用。
// breakout 降级 2 级导航研究后（S146），CV 重定向涨停叉内：涨停∩非涨停 by 构造 disjoint
// （非涨停=板块TOP非涨停股 vs 涨停股池），breakout 曾是唯一可交集第二输入，现移研究；
// CV 改 final∩scored（都涨停股有交集——过八项 ∩ 命中战法 = 双重确认）。
// 工程底线：不臆造——query 无数据返空数组；loading 返空数组 + isLoading=true。

import { usePreMarketBriefing } from "@/lib/query";

export type CrossValidationGroup = "dual" | "funnelOnly" | "strategyOnly";

/** 交叉验证单条候选（涨停叉内：漏斗终选 ∩ 战法命中）。 */
export interface CrossValidationItem {
  code: string;
  name: string;
  /** 漏斗终选侧：gene_score.total_score（final_candidates 有则填） */
  geneScore?: number;
  /** 战法侧：命中的战法名（scored_candidates 有则填，多战法取首个） */
  strategyName?: string;
  /** 战法分 */
  strategyScore?: number;
  /** 数据来源标记：dual / funnelOnly / strategyOnly */
  source: CrossValidationGroup;
}

export interface CrossValidationGroups {
  dual: CrossValidationItem[];
  funnelOnly: CrossValidationItem[];
  strategyOnly: CrossValidationItem[];
  isLoading: boolean;
}

/**
 * 涨停叉内交叉验证：final_candidates(漏斗终选) ∩ scored_candidates(战法命中)。
 * dual=双重确认（过八项且命中战法）/ funnelOnly=仅漏斗终选 / strategyOnly=仅战法命中。
 * 纯函数——供 PipelineFlow（已持 briefing prop）inline 调用 + useCrossValidationGroups hook 复用（DRY）。
 */
export function computeLimitupInternalCV(
  finals: { code: string; name: string; gene_score?: { total_score?: number } | null }[] | undefined,
  scored: { code: string; name: string; strategy_name?: string; strategy_score?: number }[] | undefined,
): CrossValidationGroups {
  const finalMap = new Map<string, CrossValidationItem>();
  for (const c of finals ?? []) {
    finalMap.set(c.code, {
      code: c.code, name: c.name,
      geneScore: c.gene_score?.total_score, source: "funnelOnly",
    });
  }
  const scoredMap = new Map<string, CrossValidationItem>();
  for (const s of scored ?? []) {
    scoredMap.set(s.code, {
      code: s.code, name: s.name,
      strategyName: s.strategy_name, strategyScore: s.strategy_score, source: "strategyOnly",
    });
  }
  const dual: CrossValidationItem[] = [];
  const funnelOnly: CrossValidationItem[] = [];
  const strategyOnly: CrossValidationItem[] = [];
  for (const [code, fItem] of finalMap) {
    const sItem = scoredMap.get(code);
    if (sItem) dual.push({ ...fItem, ...sItem, source: "dual" });
    else funnelOnly.push(fItem);
  }
  for (const [code, sItem] of scoredMap) {
    if (!finalMap.has(code)) strategyOnly.push(sItem);
  }
  return { dual, funnelOnly, strategyOnly, isLoading: false };
}

/**
 * 交叉验证分组 hook（涨停叉内：final ∩ scored）。
 * breakout 降级研究后不再取 breakout——final_candidates + scored_candidates 都从 briefing 取。
 * @param F 前瞻数据日（briefing 数据源）
 */
export function useCrossValidationGroups(F: string): CrossValidationGroups {
  const query = usePreMarketBriefing(F);
  if (query.isLoading) {
    return { dual: [], funnelOnly: [], strategyOnly: [], isLoading: true };
  }
  if (!query.data) {
    return { dual: [], funnelOnly: [], strategyOnly: [], isLoading: false };
  }
  return { ...computeLimitupInternalCV(query.data.final_candidates, query.data.scored_candidates), isLoading: false };
}
