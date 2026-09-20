import type { Metadata } from "next";

import { CommandCenter } from "@/components/workspace/command-center/command-center";

export const metadata: Metadata = { title: "Command Center | Momentum" };

export default function CommandCenterPage() {
  return <CommandCenter />;
}
