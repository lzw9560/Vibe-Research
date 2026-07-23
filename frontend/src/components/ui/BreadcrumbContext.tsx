import { createContext, useContext } from "react";
import type { BreadcrumbItem } from "./Breadcrumbs";

interface BreadcrumbContextValue {
  items: BreadcrumbItem[];
  setItems: (items: BreadcrumbItem[]) => void;
}

export const BreadcrumbContext = createContext<BreadcrumbContextValue>({
  items: [],
  setItems: () => {},
});

export function useBreadcrumbs() {
  return useContext(BreadcrumbContext);
}
