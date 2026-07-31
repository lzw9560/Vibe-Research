import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { router } from "./router";
import "./index.css";

// S013 T11：注入 QueryClientProvider（TanStack Query）——管 server state（缓存/去重/后台刷新），
// 为后续 T8/T9 各域 query hooks 替手写 loading/effect 铺地基。
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s 内不重复请求（SWR 风格）
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" theme="dark" richColors closeButton duration={3500} />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
);
