// S179 Phase 0 P0.1: currentStock 跨页状态 store（React Context + useReducer，零依赖）。
// 选股→个股→右侧面板联动（Bloomberg Linking）。按 selector 拆 context 缓 13 寸密集 cockpit 重渲染（grill F6）。
import { createContext, useContext, useReducer, useCallback, type ReactNode } from "react";

export interface CurrentStock {
  code: string | null;
  name: string | null;
  source: string | null; // 来源页（screener/watchlist/...）
  browsedAt: string[]; // 最近浏览 code（/stock/:code 无 code 时 fallback，grill #13）
}

const initial: CurrentStock = { code: null, name: null, source: null, browsedAt: [] };

type Action =
  | { type: "select"; code: string; name?: string; source?: string }
  | { type: "clear" };

function reducer(state: CurrentStock, action: Action): CurrentStock {
  switch (action.type) {
    case "select": {
      const browsedAt = [action.code, ...state.browsedAt.filter((c) => c !== action.code)].slice(0, 20);
      return {
        code: action.code,
        name: action.name ?? null,
        source: action.source ?? null,
        browsedAt,
      };
    }
    case "clear":
      return { ...state, code: null, name: null, source: null };
  }
}

const CurrentStockContext = createContext<CurrentStock>(initial);
const CurrentStockDispatchContext = createContext<(a: Action) => void>(() => {});

export function CurrentStockProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  return (
    <CurrentStockContext.Provider value={state}>
      <CurrentStockDispatchContext.Provider value={dispatch}>
        {children}
      </CurrentStockDispatchContext.Provider>
    </CurrentStockContext.Provider>
  );
}

export function useCurrentStock(): CurrentStock {
  return useContext(CurrentStockContext);
}

export function useSelectStock(): (code: string, name?: string, source?: string) => void {
  const dispatch = useContext(CurrentStockDispatchContext);
  return useCallback(
    (code: string, name?: string, source?: string) => dispatch({ type: "select", code, name, source }),
    [dispatch],
  );
}
