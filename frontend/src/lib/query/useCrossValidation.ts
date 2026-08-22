// S093 T12：共享交集 hook——漏斗 final_candidates ∩ breakout top-N 三组分组。
// 前瞻④交叉验证徽章 + 当日 WatchlistBoard 复用（spec R4④ + R6）。
// 工程底线：不臆造——query 无数据返空数组；任一 loading 返空数组 + isLoading=true。
// 两侧 code 均为裸 6 位码，交集可行（spec R4④）。

import { usePreMarketBriefing } from "@/lib/query";
import { usePremarketSelection } from "@/lib/query/premarket";

export type CrossValidationGroup = "dual" | "funnelOnly" | "breakoutOnly";

export interface CrossValidationGroups {
  /** 漏斗∩breakout 双重确认 */
  dual: string[];
  /** 仅漏斗有 */
  funnelOnly: string[];
  /** 仅 breakout 有 */
  breakoutOnly: string[];
  /** 任一 query loading → true + 三组空数组 */
  isLoading: boolean;
}

/**
 * 交叉验证分组 hook。
 *
 * @param F 前瞻数据日（漏斗 final_candidates 数据源）
 * @param forward forward 日期（breakout 候选数据源，T-1=F 的 close 算 breakout 分数）
 * @returns dual/funnelOnly/breakoutOnly 三组 code 列表 + isLoading
 */
export function useCrossValidationGroups(F: string, forward: string): CrossValidationGroups {
  const funnelQuery = usePreMarketBriefing(F);
  const breakoutQuery = usePremarketSelection(forward);

  const isLoading = funnelQuery.isLoading || breakoutQuery.isLoading;

  // query 无数据 → 空集合（不臆造）
  const funnelCodes = new Set(
    funnelQuery.data?.final_candidates?.map((c) => c.code) ?? [],
  );
  const breakoutCodes = new Set(
    breakoutQuery.data?.candidates?.map((c) => c.code) ?? [],
  );

  // 任一 loading → 三组空 + isLoading=true
  if (isLoading) {
    return { dual: [], funnelOnly: [], breakoutOnly: [], isLoading: true };
  }

  const dual: string[] = [];
  const funnelOnly: string[] = [];
  const breakoutOnly: string[] = [];

  for (const code of funnelCodes) {
    if (breakoutCodes.has(code)) {
      dual.push(code);
    } else {
      funnelOnly.push(code);
    }
  }
  for (const code of breakoutCodes) {
    if (!funnelCodes.has(code)) {
      breakoutOnly.push(code);
    }
  }

  return { dual, funnelOnly, breakoutOnly, isLoading: false };
}
