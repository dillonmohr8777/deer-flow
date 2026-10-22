"use client";

import { PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

export function WorkspaceSidebarTrigger({
  className,
  onClick,
  ...props
}: React.ComponentProps<typeof Button>) {
  const { isMobile, open, openMobile, toggleSidebar } = useSidebar();
  const isOpen = isMobile ? openMobile : open;

  return (
    <Button
      data-sidebar="trigger"
      data-slot="sidebar-trigger"
      variant="ghost"
      size="icon"
      className={cn(
        "text-muted-foreground hover:text-foreground size-10",
        className,
      )}
      onClick={(event) => {
        onClick?.(event);
        toggleSidebar();
      }}
      {...props}
    >
      {isOpen ? <PanelLeftCloseIcon /> : <PanelLeftOpenIcon />}
      <span className="sr-only">Toggle Sidebar</span>
    </Button>
  );
}
