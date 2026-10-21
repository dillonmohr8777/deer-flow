import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
import { fetch } from "@/core/api/fetcher";
import { useWorkspaceSelection } from "@/core/workspaces/hooks";

const request = rs.mocked(fetch);
function wrapper({ children }: PropsWithChildren) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  request.mockReset();
});

test("personal handoff uses the CSRF fetcher then discards the prior workspace page", async () => {
  const navigate = rs
    .spyOn(window.location, "assign")
    .mockImplementation(() => undefined);
  request
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ active_workspace_id: "momentum", workspaces: [] }),
      ),
    )
    .mockResolvedValueOnce(new Response("{}"));
  const { result } = renderHook(() => useWorkspaceSelection(), { wrapper });
  await waitFor(() =>
    expect(result.current.data?.active_workspace_id).toBe("momentum"),
  );
  await act(() => result.current.selectWorkspace(null));
  expect(request).toHaveBeenLastCalledWith("/api/workspaces/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workspace_id: null }),
  });
  expect(navigate).toHaveBeenCalledWith("/workspace/chats");
});

test("failed workspace selection reports failure and keeps the current page", async () => {
  const navigate = rs
    .spyOn(window.location, "assign")
    .mockImplementation(() => undefined);
  request
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ active_workspace_id: "momentum", workspaces: [] }),
      ),
    )
    .mockResolvedValueOnce(new Response("{}", { status: 503 }));
  const { result } = renderHook(() => useWorkspaceSelection(), { wrapper });
  await waitFor(() => expect(result.current.data).toBeTruthy());
  await act(async () => {
    await expect(result.current.selectWorkspace(null)).rejects.toThrow(
      "Couldn't switch workspace",
    );
  });
  expect(navigate).not.toHaveBeenCalled();
});
