// lib/auction.ts — 竞价窗口公共常量与工作日判定（S025-B 去重复）。
// 消费方：Monitor925.getNextAuctionWindow（窗口倒计时）+ query/limitup.isInAuctionWindow（轮询开关）。
// 两处原先各自硬编码 9*60+15 / 9*60+30 与工作日判定，抽此复用。

/** 竞价窗口开始：9:15（当日分钟数，9*60+15 = 555）。 */
export const AUCTION_START_MIN = 9 * 60 + 15;

/** 竞价窗口结束：9:30（当日分钟数，9*60+30 = 570）。 */
export const AUCTION_END_MIN = 9 * 60 + 30;

/**
 * 工作日判定：周一(1)至周五(5) 为工作日，周六(6)/周日(0) 为非工作日。
 * A 股竞价窗口仅工作日开放。
 */
export function isWeekday(date: Date): boolean {
  const day = date.getDay();
  return day >= 1 && day <= 5;
}
