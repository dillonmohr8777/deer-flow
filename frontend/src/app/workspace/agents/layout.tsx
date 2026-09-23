"use client";

import type { ReactNode } from "react";

import { AgentsFeatureDisabled } from "@/components/workspace/agents/agents-feature-disabled";
import { WorkingState } from "@/components/workspace/page-body";
import { useAgentsApiEnabled } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

export default function AgentsLayout({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { enabled, isLoading } = useAgentsApiEnabled();

  if (isLoading) {
    return (
      <div className="flex size-full items-center justify-center">
        <WorkingState label={t.common.loading} />
      </div>
    );
  }

  if (!enabled) {
    return <AgentsFeatureDisabled />;
  }

  return <>{children}</>;
}
