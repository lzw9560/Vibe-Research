// S093 T12：共享交集 hook——漏斗 final_candidates ∩ breakout top-N 三组分组。
// 前瞻④交叉验证徽章 + 当日 WatchlistBoard 复用（spec R4④ + R6）。
// 工程底线：不臆造——query 无数据返空数组；任一 loading 返空数组 + isLoading=true。
// 两侧 code 均为裸 6 位码，交集可行（spec R4④）。
// S094 改造：返回富对象（code+name+score+strategy+source）替代裸 code string[]，
// 供 CrossValidationSummary 渲染详情行。

import { usePreMarketBriefing } from "@/lib/query";
import { usePremarketSelection } from "@/lib/query/premarket";

export type CrossValidationGroup = "dual" | "funnelOnly" | "breakoutOnly";

/** 交叉验证单条候选（富对象，含 name/score/strategy 供详情渲染）。 */
export interface CrossValidationItem {
  code: string;
  name: string;
  /** 漏斗侧：gene_score.total_score（漏斗有则填） */
  geneScore?: number;
  /** 战法侧：命中的战法名（scored_candidates 有则填，多战法取首个） */
  strategyName?: string;
  /** 战法分 */
  strategyScore?: number;
  /** breakout 侧分数（breakout 有则填） */
  breakoutScore?: number;
  /** 数据来源标记：funnel / breakout / dual */
  source: CrossValidationGroup;
}

export interface CrossValidationGroups {
  dual: CrossValidationItem[];
  funnelOnly: CrossValidationItem[];
  breakoutOnly: CrossValidationItem[];
  isLoading: boolean;
}

/**
 * 交叉验证分组 hook。
 *
 * @param F 前瞻数据日（漏斗 final_candidates 数据源）
 * @param forward forward 日期（breakout 候选数据源，T-1=F 的 close 算 breakout 分数）
 * @returns dual/funnelOnly/breakoutOnly 三组富对象列表 + isLoading
 */
export function useCrossValidationGroups(F: string, forward: string): CrossValidationGroups {
  const funnelQuery = usePreMarketBriefing(F);
  const breakoutQuery = usePremarketSelection(forward);

  const isLoading = funnelQuery.isLoading || breakoutQuery.isLoading;

  if (isLoading) {
    return { dual: [], funnelOnly: [], breakoutOnly: [], isLoading: true };
  }

  // 漏斗侧：final_candidates → {code, name, geneScore}
  const funnelMap = new Map<string, CrossValidationItem>();
  for (const c of funnelQuery.data?.final_candidates ?? []) {
    const geneScoreObj = (c as unknown as Record<string, unknown>).gene_score as Record<string, number> | undefined;
    funnelMap.set(c.code, {
      code: c.code,
      name: c.name,
      geneScore: geneScoreObj?.total_score,
      source: "funnelOnly",
    });
  }

  // 战法侧：scored_candidates → 补 strategyName/strategyScore（一只多战法取首）
  for (const s of funnelQuery.data?.scored_candidates ?? []) {
    const existing = funnelMap.get(s.code);
    if (existing && !existing.strategyName) {
      existing.strategyName = s.strategy_name;
      existing.strategyScore = s.strategy_score;
    }
  }

  // breakout 侧：candidates → {code, name, breakoutScore, matched_strategy}
  const breakoutMap = new Map<string, CrossValidationItem>();
  for (const c of breakoutQuery.data?.candidates ?? []) {
    const brk = c as unknown as Record<string, unknown>;
    breakoutMap.set(c.code, {
      code: c.code,
      name: c.name,
      breakoutScore: brk.score as number | undefined,
      strategyName: brk.matched_strategy as string | undefined,
      source: "breakoutOnly",
    });
  }

  // 交集分组
  const dual: CrossValidationItem[] = [];
  const funnelOnly: CrossValidationItem[] = [];
  const breakoutOnly: CrossValidationItem[] = [];

  for (const [code, funnelItem] of funnelMap) {
    const brk = breakoutMap.get(code);
    if (brk) {
      dual.push({
        ...funnelItem,
        breakoutScore: brk.breakoutScore,
        source: "dual",
      });
    } else {
      funnelOnly.push(funnelItem);
    }
  }
  for (const [code, brkItem] of breakoutMap) {
    if (!funnelMap.has(code)) {
      breakoutOnly.push(brkItem);
    }
  }

  return { dual, funnelOnly, breakoutOnly, isLoading: false };
}
