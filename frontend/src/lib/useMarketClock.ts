// S092 R14：双定时器 hook（服务器时间驱动）+ 过渡窗轮询。
//
// 核心：用 next_*_at（epoch 秒，后端算）减 Date.now() 得 setTimeout 延时，
// 到点触发推进。**不依赖本地时钟判断北京时间**——消除 H1 时区 bug
// （非北京时区用户本地 15:00 ≠ 北京 15:00）。
//
// - 15:00 定时器（next_review_advance_at）：交易日到点推进复盘视图数据日到 T（R2a），不推进 F
// - 17:15 定时器（next_f_advance_at）：交易日到点推进 F + 全量刷新三视图（R2）
// - non_trading=true 跳过两个定时器（非交易日不推进）
// - is_manual=true（用户手动选了 date 覆盖 F）跳过两个定时器——避免覆盖手动选择（R14）
// - delay <= 0（已过时刻）或 > 12h（异常值）跳过——防回拨时钟或脏数据触发即时/超长定时器
//
// 到点后 invalidate ["workflow","date-triplet"] 让 useDateTriplet refetch 拿新 stage/
// review_advanced；消费方 onFAdvance 可触发三视图各自 refetch。

import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

export interface UseMarketClockOptions {
  /** 下次复盘推进（15:00）的 epoch 秒（后端算，北京时区锚定） */
  next_review_advance_at: number;
  /** 下下次 F 推进（17:15）的 epoch 秒 */
  next_f_advance_at: number;
  /** 非交易日 → 跳过两个定时器 */
  non_trading: boolean;
  /** 用户手动选了 date 覆盖 F → 定时器不推进（R14） */
  is_manual: boolean;
  /** 15:00 回调（推进复盘视图数据日到 T） */
  onReviewAdvance?: () => void;
  /** 17:15 回调（推进 F + 全量刷新三视图） */
  onFAdvance?: () => void;
}

// delay 上限 12h——防 next_*_at 是异常脏数据（如 0 或未来一年）触发即时或超长定时器。
const MAX_DELAY_MS = 12 * 3600 * 1000;

export function useMarketClock(opts: UseMarketClockOptions): void {
  const qc = useQueryClient();

  // 用 ref 存回调，避免回调变更导致定时器重建（丢已累积的延时）。
  // 惯例参照 hooks/useDebounce：effect 依赖稳定，ref 跟踪可变值。
  const onReviewRef = useRef(opts.onReviewAdvance);
  const onFRef = useRef(opts.onFAdvance);
  useEffect(() => {
    onReviewRef.current = opts.onReviewAdvance;
  }, [opts.onReviewAdvance]);
  useEffect(() => {
    onFRef.current = opts.onFAdvance;
  }, [opts.onFAdvance]);

  // invalidate 用稳定引用（qc 来自 useQueryClient，稳定；queryKey 字面量稳定），
  // 故 effect 依赖只列 next_*_at / non_trading / is_manual——这三者变更意味推进点变了，需重建定时器。
  const invalidateTriplet = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["workflow", "date-triplet"] });
  }, [qc]);

  // 15:00 复盘推进定时器
  useEffect(() => {
    if (opts.non_trading || opts.is_manual) return;
    const delay = opts.next_review_advance_at * 1000 - Date.now();
    if (delay <= 0 || delay > MAX_DELAY_MS) return;
    const timer = setTimeout(() => {
      onReviewRef.current?.();
      invalidateTriplet();
    }, delay);
    return () => clearTimeout(timer);
  }, [opts.next_review_advance_at, opts.non_trading, opts.is_manual, invalidateTriplet]);

  // 17:15 F 推进定时器
  useEffect(() => {
    if (opts.non_trading || opts.is_manual) return;
    const delay = opts.next_f_advance_at * 1000 - Date.now();
    if (delay <= 0 || delay > MAX_DELAY_MS) return;
    const timer = setTimeout(() => {
      onFRef.current?.();
      invalidateTriplet();
    }, delay);
    return () => clearTimeout(timer);
  }, [opts.next_f_advance_at, opts.non_trading, opts.is_manual, invalidateTriplet]);
}
