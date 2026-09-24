import type { Metadata } from "next";

import { CommandCenter } from "@/components/workspace/command-center/command-center";

export const metadata: Metadata = { title: "Command Center | MomoBot" };

export default function CommandCenterPage() {
  return <CommandCenter />;
}
