import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      workspace: {
        noPhiBanner: "Please don't share patient or health information here.",
        noPhiBannerDetail:
          "This workspace is for marketing work only, and file uploads are turned off.",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

import { NoPhiBanner } from "@/components/workspace/no-phi-banner";
import { fetch } from "@/core/api/fetcher";

const mockedFetch = rs.mocked(fetch);

function workspaceList(extra: Record<string, unknown>) {
  return {
    ok: true,
    json: () =>
      Promise.resolve({
        workspaces: [],
        active_workspace_id: null,
        ...extra,
      }),
  } as unknown as Response;
}

function renderBanner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<NoPhiBanner />, { wrapper });
}

describe("NoPhiBanner", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });
  afterEach(cleanup);

  it("shows the no-patient-information notice in a health-sector workspace", async () => {
    mockedFetch.mockResolvedValue(workspaceList({ active_no_phi: true }));
    renderBanner();

    const banner = await screen.findByTestId("no-phi-banner");
    expect(banner.textContent).toContain(
      "Please don't share patient or health information here.",
    );
    expect(banner.textContent).toContain("file uploads are turned off");
    expect(mockedFetch.mock.calls[0]?.[0]).toBe("/api/workspaces");
  });

  it("stays on screen: there is nothing to dismiss", async () => {
    mockedFetch.mockResolvedValue(workspaceList({ active_no_phi: true }));
    renderBanner();

    await screen.findByTestId("no-phi-banner");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("renders nothing in an ordinary workspace", async () => {
    mockedFetch.mockResolvedValue(workspaceList({ active_no_phi: false }));
    renderBanner();

    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("no-phi-banner")).toBeNull();
  });

  it("renders nothing when an older gateway omits the flag", async () => {
    mockedFetch.mockResolvedValue(workspaceList({}));
    renderBanner();

    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("no-phi-banner")).toBeNull();
  });
});
