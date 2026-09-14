// Track D M6: 焦点日全局切——跨页共享 focus day（T-1/T/T+1）。
// 镜像 currentStock 范式（React Context，零依赖）。focusDate 是纯标量替换（无派生态），
// 故用 useState 比 useReducer 更直白。
// 今日 hub 设焦点日 → 复盘/持仓/盘面 各页读同一 focusDate 传 useDateTriplet(focusDate)
// → queryKey 含 focusDate，切日自动 refetch（跟切重拉）。null = 自动模式（按时段算）。
import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export interface FocusDayState {
  /** 用户手动选的复盘日（YYYY-MM-DD）；null = 自动模式（useDateTriplet 不传 date） */
  focusDate: string | null;
}

const initial: FocusDayState = { focusDate: null };

const FocusDayContext = createContext<FocusDayState>(initial);
const FocusDaySetterContext = createContext<(date: string | null) => void>(() => {});

export function FocusDayProvider({ children }: { children: ReactNode }) {
  const [focusDate, setFocusDate] = useState<string | null>(null);
  const setter = useCallback((date: string | null) => setFocusDate(date), []);
  return (
    <FocusDayContext.Provider value={{ focusDate }}>
      <FocusDaySetterContext.Provider value={setter}>
        {children}
      </FocusDaySetterContext.Provider>
    </FocusDayContext.Provider>
  );
}

export function useFocusDay(): FocusDayState {
  return useContext(FocusDayContext);
}

/** 设焦点日（传日期串）或清回自动（传 null）。 */
export function useSetFocusDay(): (date: string | null) => void {
  return useContext(FocusDaySetterContext);
}
