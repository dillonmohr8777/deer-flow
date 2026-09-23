import { afterEach, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

import { AgentCard } from "@/components/workspace/agents/agent-card";
import type { Agent } from "@/core/agents";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
}));
rs.mock("@/core/agents", () => ({
  useDeleteAgent: () => ({ mutateAsync: rs.fn(), isPending: false }),
  useUpdateAgent: () => ({ mutateAsync: rs.fn(), isPending: false }),
}));
rs.mock("@/core/features", () => ({
  useKnowledgeBaseEnabled: () => ({ scopeSelectionEnabled: false }),
}));
rs.mock("@/core/models/hooks", () => ({ useModels: () => ({ models: [] }) }));
rs.mock("@/core/subagents", () => ({
  useSubagents: () => ({ subagents: [] }),
}));
rs.mock("@/core/capabilities/hooks", () => ({
  useCapabilityInstallations: () => ({
    data: { items: [], can_manage: false },
    isLoading: false,
    isError: false,
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

const agent: Agent = {
  name: "analytics-engineer",
  display_name: "Analytics Engineer",
  description: "Builds reconciled metrics.",
  model: "openrouter-muse-spark-contributor",
  tool_groups: ["file:read", "bash"],
  skills: null,
};

afterEach(cleanup);

function renderRow() {
  return render(
    <ul>
      <AgentCard agent={agent} />
    </ul>,
  );
}

it("shows the model's display name, never the slug or its tier word", () => {
  const { container } = renderRow();
  expect(
    screen.getByRole("heading", { name: "Analytics Engineer" }),
  ).toBeDefined();
  expect(screen.getByText("Muse Spark 1.3")).toBeDefined();
  expect(container.textContent).not.toMatch(/contributor|openrouter/i);
  expect(screen.getByText("file:read")).toBeDefined();
});

it("keeps delete one step back, inside the agent's settings", () => {
  renderRow();
  expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
  const settings = screen.getByTitle("Agent settings");
  expect(settings.getAttribute("aria-label")).toBe(
    "Agent settings: Analytics Engineer",
  );
  fireEvent.click(settings);
  const dialog = screen.getByRole("dialog", { name: "Agent settings" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(screen.getByText(enUS.agents.deleteConfirm)).toBeDefined();
});
