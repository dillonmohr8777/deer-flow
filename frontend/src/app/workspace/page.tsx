import { redirect } from "next/navigation";

import { isDeskEnabledOnServer } from "@/core/features/server";
import { DEMO_THREAD_IDS } from "@/core/threads/static-demo";
import { env } from "@/env";

export default async function WorkspacePage() {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return redirect(`/workspace/chats/${DEMO_THREAD_IDS[0]}`);
  }
  // The owner's private instance opens on Desk; every other instance keeps
  // Command Center as home.
  return redirect(
    (await isDeskEnabledOnServer())
      ? "/workspace/desk"
      : "/workspace/command-center",
  );
}
