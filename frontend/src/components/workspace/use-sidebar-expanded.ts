"use client";

import { useSidebar } from "@/components/ui/sidebar";

export function useSidebarExpanded() {
  const { isMobile, open } = useSidebar();
  return isMobile || open;
}
