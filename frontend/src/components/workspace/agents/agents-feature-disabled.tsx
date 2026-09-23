"use client";

import { EmptyState } from "@/components/workspace/page-body";
import { useI18n } from "@/core/i18n/hooks";

export function AgentsFeatureDisabled() {
  const { t } = useI18n();
  return (
    <div className="flex size-full items-center justify-center p-6">
      <EmptyState momo="verifier" title={t.agents.featureDisabledTitle}>
        {t.agents.featureDisabledDescription}
      </EmptyState>
    </div>
  );
}
