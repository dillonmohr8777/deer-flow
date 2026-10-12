"use client";

import { MomoAvatar } from "@/components/workspace/command-center/momo-avatar";
import { type Agent } from "@/core/agents";
import { cn } from "@/lib/utils";

export function AgentWelcome({
  className,
  agent,
  agentName,
}: {
  className?: string;
  agent: Agent | null | undefined;
  agentName: string;
}) {
  const displayName = agent?.display_name?.length
    ? agent.display_name
    : (agent?.name ?? agentName);
  const description = agent?.description;

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-8 py-4 text-center",
        className,
      )}
    >
      {/* One avatar per agent: the Momo the roster and Command Center draw.
          The name is the heading below, so the mark is not announced. Phones
          get the 48px mark: the welcome grows upward from the composer and a
          larger one would slide under the header. */}
      <span className="mb-1 sm:hidden">
        <MomoAvatar agent={agent ?? { name: agentName }} size={48} decorative />
      </span>
      <span className="mb-1 hidden sm:block">
        <MomoAvatar agent={agent ?? { name: agentName }} size={72} decorative />
      </span>
      <div className="text-2xl font-bold">{displayName}</div>
      {description && (
        <p className="text-muted-foreground max-w-sm text-sm">{description}</p>
      )}
    </div>
  );
}
