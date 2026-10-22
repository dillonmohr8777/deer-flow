import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/agents/api", () => ({
  createAgent: rs.fn(),
  deleteAgent: rs.fn(),
  fetchAgentsApiEnabled: rs.fn(),
  getAgent: rs.fn(),
  listAgents: rs.fn(),
  updateAgent: rs.fn(),
}));

import { fetchAgentsApiEnabled, listAgents } from "@/core/agents/api";
import { useAgents } from "@/core/agents/hooks";

const mockedFetchAgentsApiEnabled = rs.mocked(fetchAgentsApiEnabled);
const mockedListAgents = rs.mocked(listAgents);
const cacheKey = "deerflow.features.agents_api";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function createHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

beforeEach(() => {
  localStorage.removeItem(cacheKey);
  mockedFetchAgentsApiEnabled.mockReset();
  mockedListAgents.mockReset();
});

afterEach(() => {
  cleanup();
  localStorage.removeItem(cacheKey);
});

describe("useAgents feature gating", () => {
  it("waits for feature discovery and skips the list request when disabled", async () => {
    const feature = deferred<boolean>();
    mockedFetchAgentsApiEnabled.mockReturnValue(feature.promise);
    mockedListAgents.mockResolvedValue([]);
    const { queryClient, wrapper } = createHarness();

    const { result } = renderHook(() => useAgents(), { wrapper });

    expect(result.current.isLoading).toBe(true);
    expect(mockedListAgents).not.toHaveBeenCalled();
    await act(async () => {
      feature.resolve(false);
      await feature.promise;
    });
    await waitFor(() =>
      expect(queryClient.getQueryData(["features", "agents_api"])).toBe(false),
    );

    expect(mockedListAgents).not.toHaveBeenCalled();
  });

  it("does not refetch agents when a background feature recheck confirms enabled", async () => {
    const feature = deferred<boolean>();
    mockedFetchAgentsApiEnabled
      .mockResolvedValueOnce(true)
      .mockReturnValueOnce(feature.promise);
    mockedListAgents.mockResolvedValue([]);
    const { queryClient, wrapper } = createHarness();

    renderHook(() => useAgents(), { wrapper });

    await waitFor(() => expect(mockedListAgents).toHaveBeenCalledTimes(1));
    act(() => {
      void queryClient.invalidateQueries({
        queryKey: ["features", "agents_api"],
      });
    });
    await waitFor(() =>
      expect(mockedFetchAgentsApiEnabled).toHaveBeenCalledTimes(2),
    );
    expect(mockedListAgents).toHaveBeenCalledTimes(1);

    await act(async () => {
      feature.resolve(true);
      await feature.promise;
    });
    await waitFor(() =>
      expect(queryClient.getQueryData(["features", "agents_api"])).toBe(true),
    );

    expect(mockedListAgents).toHaveBeenCalledTimes(1);
  });

  it("starts the list request after feature discovery enables the API", async () => {
    const feature = deferred<boolean>();
    mockedFetchAgentsApiEnabled.mockReturnValue(feature.promise);
    mockedListAgents.mockResolvedValue([]);
    const { wrapper } = createHarness();

    renderHook(() => useAgents(), { wrapper });

    expect(mockedListAgents).not.toHaveBeenCalled();
    await act(async () => {
      feature.resolve(true);
      await feature.promise;
    });

    await waitFor(() => expect(mockedListAgents).toHaveBeenCalledTimes(1));
  });

  it("keeps a cached disabled flag through feature-discovery failure", async () => {
    localStorage.setItem(cacheKey, "false");
    mockedFetchAgentsApiEnabled.mockRejectedValue(new Error("offline"));
    const { queryClient, wrapper } = createHarness();

    renderHook(() => useAgents(), { wrapper });

    await waitFor(() =>
      expect(
        queryClient.getQueryState(["features", "agents_api"])?.status,
      ).toBe("error"),
    );
    expect(mockedListAgents).not.toHaveBeenCalled();
  });

  it("returns no cached agents after the feature is confirmed disabled", async () => {
    const feature = deferred<boolean>();
    const cachedAgents = [
      {
        name: "cached-agent",
        description: "Cached agent",
        model: null,
        tool_groups: null,
        skills: null,
      },
    ];
    mockedFetchAgentsApiEnabled.mockReturnValue(feature.promise);
    const { queryClient, wrapper } = createHarness();
    queryClient.setQueryData(["agents"], cachedAgents);

    const { result } = renderHook(() => useAgents(), { wrapper });
    await act(async () => {
      feature.resolve(false);
      await feature.promise;
    });

    await waitFor(() =>
      expect(queryClient.getQueryData(["features", "agents_api"])).toBe(false),
    );
    expect(queryClient.getQueryData(["agents"])).toEqual(cachedAgents);
    expect(result.current.agents).toEqual([]);
    expect(mockedListAgents).not.toHaveBeenCalled();
  });

  it("preserves the fail-open default when no flag has been observed", async () => {
    mockedFetchAgentsApiEnabled.mockRejectedValue(new Error("offline"));
    mockedListAgents.mockResolvedValue([]);
    const { wrapper } = createHarness();

    renderHook(() => useAgents(), { wrapper });

    await waitFor(() => expect(mockedListAgents).toHaveBeenCalledTimes(1));
  });
});
