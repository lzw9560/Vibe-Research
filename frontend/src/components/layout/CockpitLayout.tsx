import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Outlet } from "react-router-dom";
import { SplitLayout } from "./SplitLayout";

/**
 * CockpitLeftContext — 让 CockpitLayout 子页面（经 Outlet 渲染）注入左栏内容。
 *
 * value = setLeft（useState 的 setter，引用稳定，不触发多余重渲染）。
 * 页面通过 useCockpitLeft(node) 注册左栏；卸载时 cleanup 清空回默认占位。
 */
const CockpitLeftContext = createContext<
  (node: ReactNode | null) => void
>(() => {});

/**
 * CockpitLayout — 双 Layout 之 cockpit 版。
 *
 * SplitLayout 包裹 Outlet：右栏 = 路由页内容，左栏 = 页面经 useCockpitLeft 注入。
 * 用于 /market /stock/:code /intraday /multiline 等双焦点 cockpit 页（spec §5.2）。
 *
 * 用法（router.tsx 嵌套路由）：
 *   {
 *     element: <CockpitLayout />,
 *     children: [
 *       { path: "/market", element: <MarketPage /> },
 *       { path: "/stock/:code", element: <StockCockpit /> },
 *     ],
 *   }
 *
 * 页面注入左栏：
 *   function MarketPage() {
 *     useCockpitLeft(<MarketList />);
 *     return <MarketDetail />;  // 渲染在右栏（Outlet 位置）
 *   }
 */
export function CockpitLayout() {
  const [left, setLeft] = useState<ReactNode | null>(null);

  return (
    <CockpitLeftContext.Provider value={setLeft}>
      <SplitLayout
        left={left ?? <DefaultCockpitLeft />}
        right={<Outlet />}
      />
    </CockpitLeftContext.Provider>
  );
}

/**
 * useCockpitLeft — cockpit 子页面注入左栏内容的 hook。
 *
 * @param node 左栏 ReactNode（传 null 清空回默认占位）
 *
 * @example
 * useCockpitLeft(<StockList stocks={data} onSelect={...} />);
 *
 * 注意：若 node 是内联 JSX（每次 render 新引用），effect 会每次 run
 * 触发 setLeft。页面可用 useMemo 包裹 node 避免不必要重渲染。
 */
export function useCockpitLeft(node: ReactNode | null): void {
  const setLeft = useContext(CockpitLeftContext);
  useEffect(() => {
    setLeft(node);
    return () => setLeft(null);
  }, [node, setLeft]);
}

/** 默认左栏占位 — 无页面注入时显示 */
function DefaultCockpitLeft() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
      <p className="text-sm font-medium text-muted-foreground">列表区</p>
      <p className="text-xs text-muted-foreground/60">页面填充左栏内容</p>
    </div>
  );
}
