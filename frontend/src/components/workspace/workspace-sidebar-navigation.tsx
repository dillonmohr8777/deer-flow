"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { useSidebar } from "@/components/ui/sidebar";

function isNewChatThreadReplacement(
  previousPathname: string,
  pathname: string,
) {
  const previousSegments = previousPathname.split("/");
  const currentSegments = pathname.split("/");

  return (
    previousSegments.at(-2) === "chats" &&
    previousSegments.at(-1) === "new" &&
    currentSegments.length === previousSegments.length &&
    currentSegments.slice(0, -1).join("/") ===
      previousSegments.slice(0, -1).join("/") &&
    currentSegments.at(-1) !== "new"
  );
}

export function WorkspaceSidebarNavigation() {
  const { isMobile, setOpenMobile } = useSidebar();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const locationKey = `${pathname}?${searchParams.toString()}`;
  const previousLocation = useRef({ locationKey, pathname });

  useEffect(() => {
    const previous = previousLocation.current;
    if (previous.locationKey === locationKey) {
      if (!isMobile) setOpenMobile(false);
      return;
    }
    previousLocation.current = { locationKey, pathname };

    if (!isMobile || !isNewChatThreadReplacement(previous.pathname, pathname)) {
      setOpenMobile(false);
    }
  }, [isMobile, locationKey, pathname, setOpenMobile]);

  return null;
}
