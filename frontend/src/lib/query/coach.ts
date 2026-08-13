// S064：盯盘教练 TanStack Query hooks。
// 交易时段（周一至五 9:15-15:00）30s 刷新；非交易时段停拉（仿 isInAuctionWindow 函数式 refetchInterval）。
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";
import type { CoachTimetableSlot, CoachModeRules, CoachChecklistItem } from "@/lib/api";
import { isWeekday } from "@/lib/auction";

const COACH_OPEN_MIN = 9 * 60 + 15;
const COACH_CLOSE_MIN = 15 * 60;

export function isInCoachWindow(now: Date = new Date()): boolean {
  if (!isWeekday(now)) return false;
  const m = now.getHours() * 60 + now.getMinutes();
  return m >= COACH_OPEN_MIN && m < COACH_CLOSE_MIN;
}

export function useCoachTimetable(options?: Opts<{ slots: CoachTimetableSlot[]; current_slot_id: string | null; current_time: string; status: string } | null>) {
  return useQuery({
    queryKey: ["coach", "timetable"] as const,
    queryFn: () => api.coachTimetable(),
    refetchInterval: () => (isInCoachWindow() ? 30_000 : false),
    ...options,
  });
}

export function useCoachStatus(options?: Opts<{ date: string; current_time: string; current_slot: CoachTimetableSlot | null; slot_status: string; attention_mode: string; mode_rules: CoachModeRules; checklist: CoachChecklistItem[]; is_trading_day: boolean } | null>) {
  return useQuery({
    queryKey: ["coach", "status"] as const,
    queryFn: () => api.coachStatus(),
    refetchInterval: () => (isInCoachWindow() ? 30_000 : false),
    ...options,
  });
}

export function useCoachAttentionMode(options?: Opts<{ date: string; attention_mode: string; rules: CoachModeRules } | null>) {
  return useQuery({
    queryKey: ["coach", "attention-mode"] as const,
    queryFn: () => api.coachAttentionModeGet(),
    ...options,
  });
}

export function useSetCoachAttentionMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: string) => api.coachAttentionModeSet(mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["coach"] });
    },
  });
}
