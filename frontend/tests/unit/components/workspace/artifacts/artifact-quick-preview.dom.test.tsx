import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const mockState = rs.hoisted(() => ({
  userRole: "client" as "client" | "admin",
  loadArtifactContent: rs.fn(),
  writeClipboard: rs.fn().mockResolvedValue(true),
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { id: "u1", email: "fixture-user", system_role: mockState.userRole },
  }),
}));

rs.mock("@/components/workspace/artifacts/context", () => ({
  useArtifacts: () => ({ select: rs.fn(), setOpen: rs.fn() }),
}));

rs.mock("@/core/artifacts/api", () => ({
  ArtifactRequestError: Error,
  downloadArtifactArchive: rs.fn(),
  getArtifactArchiveManifest: rs.fn(),
  MAX_ARTIFACT_ARCHIVE_FILES: 50,
}));

rs.mock("@/core/artifacts/loader", () => ({
  loadArtifactContent: mockState.loadArtifactContent,
}));

rs.mock("@/core/clipboard", () => ({
  installClipboardFallback: rs.fn(),
  writeTextToClipboard: mockState.writeClipboard,
}));

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn() },
}));

import { ArtifactFileList } from "@/components/workspace/artifacts/artifact-file-list";
import {
  getArtifactQuickPreviewKind,
  parseDelimitedPreview,
} from "@/components/workspace/artifacts/artifact-quick-preview-modal";
import { ThreadContext } from "@/components/workspace/messages/context";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

function renderArtifactList(files: string[], options?: { isMock?: boolean }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const list = <ArtifactFileList files={files} threadId="thread-preview-1" />;
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        {options?.isMock !== undefined ? (
          <ThreadContext.Provider
            value={{ thread: {} as never, isMock: options.isMock }}
          >
            {list}
          </ThreadContext.Provider>
        ) : (
          list
        )}
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  mockState.loadArtifactContent.mockReset();
  mockState.writeClipboard.mockClear();
  mockState.userRole = "client";
});

describe("Artifact quick preview modal for HTML and marketing deliverables", () => {
  it("classifies supported previewable artifact extensions accurately", () => {
    expect(getArtifactQuickPreviewKind("/outputs/index.html")).toBe("html");
    expect(getArtifactQuickPreviewKind("/outputs/LANDING.HTM")).toBe("html");
    expect(getArtifactQuickPreviewKind("/outputs/blog.md")).toBe("markdown");
    expect(getArtifactQuickPreviewKind("/outputs/google-ads.csv")).toBe("csv");
    expect(getArtifactQuickPreviewKind("/outputs/keywords.tsv")).toBe("tsv");
    expect(getArtifactQuickPreviewKind("/outputs/ad-copy.txt")).toBe("text");
    expect(getArtifactQuickPreviewKind("/outputs/schema.json")).toBe("json");
    expect(getArtifactQuickPreviewKind("/outputs/archive.zip")).toBeNull();
  });

  it("opens a sandboxed iframe live preview with Desktop/Mobile toggle and Copy HTML for .html files", async () => {
    mockState.loadArtifactContent.mockResolvedValue({
      content:
        "<!doctype html><html><body><h1>Hello Local Owner</h1></body></html>",
      url: "/api/threads/thread-preview-1/artifacts/outputs/index.html",
      truncated: false,
    });

    renderArtifactList(["/mnt/user-data/outputs/index.html"]);

    // Clean Client Mode shows plain-English status
    expect(screen.getByText("Page Ready")).toBeTruthy();

    const previewBtn = screen.getByRole("button", { name: "Preview Page" });
    fireEvent.click(previewBtn);

    const iframe = await screen.findByTestId("html-artifact-preview-iframe");
    expect(iframe.getAttribute("sandbox")).toBe("allow-scripts");
    expect(iframe.getAttribute("srcdoc")).toContain("Hello Local Owner");
    expect(iframe.getAttribute("srcdoc")).toContain(
      '/api/threads/thread-preview-1/artifacts/outputs/">',
    );
    expect(iframe.getAttribute("data-viewport")).toBe("desktop");

    fireEvent.click(screen.getByRole("button", { name: "Mobile" }));
    expect(iframe.getAttribute("data-viewport")).toBe("mobile");

    fireEvent.click(screen.getByRole("button", { name: "Copy HTML" }));
    await waitFor(() => {
      expect(mockState.writeClipboard).toHaveBeenCalledWith(
        "<!doctype html><html><body><h1>Hello Local Owner</h1></body></html>",
      );
    });
  });

  it("renders a formatted table preview for CSV marketing deliverables such as Google Ads exports", async () => {
    mockState.loadArtifactContent.mockResolvedValue({
      content:
        "Ad Group,Headline 1,Headline 2\nEmergency Plumbing,24/7 Local Plumber,Fast Same-Day Service\nDrain Cleaning,Clogged Drain Fixed,Licensed & Insured",
      url: "/api/threads/thread-preview-1/artifacts/outputs/google-ads.csv",
      truncated: false,
    });

    renderArtifactList(["/mnt/user-data/outputs/google-ads.csv"]);

    expect(screen.getByText("Ready to Preview")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    const tableContainer = await screen.findByTestId("table-artifact-preview");
    expect(tableContainer.textContent).toContain("Emergency Plumbing");
    expect(tableContainer.textContent).toContain("24/7 Local Plumber");
    expect(tableContainer.textContent).toContain("2 rows");
  });

  it("renders markdown, text, and pretty-printed JSON deliverables cleanly", async () => {
    mockState.loadArtifactContent.mockResolvedValueOnce({
      content: '{"campaign":"Local Search","budget":50}',
      url: "/api/threads/thread-preview-1/artifacts/outputs/ads.json",
      truncated: false,
    });

    renderArtifactList(["/mnt/user-data/outputs/ads.json"]);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    const jsonPre = await screen.findByTestId("json-artifact-preview");
    expect(jsonPre.textContent).toContain('"campaign": "Local Search"');

    const parsed = parseDelimitedPreview("A,B\n1,2\n3,4", ",");
    expect(parsed.headers).toEqual(["A", "B"]);
    expect(parsed.rows).toEqual([
      ["1", "2"],
      ["3", "4"],
    ]);
  });

  it("forwards thread isMock status from ThreadContext into the quick preview modal loader", async () => {
    mockState.loadArtifactContent.mockResolvedValueOnce({
      content: "<h1>Mock Demo Page</h1>",
      url: "/mock/index.html",
      truncated: false,
    });

    renderArtifactList(["/mnt/user-data/outputs/index.html"], { isMock: true });
    fireEvent.click(screen.getByRole("button", { name: "Preview Page" }));

    await screen.findByTestId("html-artifact-preview-iframe");
    expect(mockState.loadArtifactContent).toHaveBeenCalledWith(
      expect.objectContaining({
        filepath: "/mnt/user-data/outputs/index.html",
        threadId: "thread-preview-1",
        isMock: true,
      }),
    );
  });

  it("disables Copy while a preview slice is truncated and enables copying once the full file loads", async () => {
    mockState.loadArtifactContent
      .mockResolvedValueOnce({
        content: "<h1>Partial Slice</h1>",
        url: "/api/threads/thread-preview-1/artifacts/outputs/big.html",
        truncated: true,
      })
      .mockResolvedValueOnce({
        content: "<h1>Complete Deliverable</h1>",
        url: "/api/threads/thread-preview-1/artifacts/outputs/big.html",
        truncated: false,
      });

    renderArtifactList(["/mnt/user-data/outputs/big.html"]);
    fireEvent.click(screen.getByRole("button", { name: "Preview Page" }));
    await screen.findByTestId("html-artifact-preview-iframe");

    const copyBtn = screen.getByRole("button", { name: "Copy HTML" });
    expect(copyBtn.hasAttribute("disabled")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Load full file" }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Copy HTML" }).hasAttribute("disabled"),
      ).toBe(false);
    });

    fireEvent.click(screen.getByRole("button", { name: "Copy HTML" }));
    await waitFor(() => {
      expect(mockState.writeClipboard).toHaveBeenCalledWith(
        "<h1>Complete Deliverable</h1>",
      );
    });
  });
});
