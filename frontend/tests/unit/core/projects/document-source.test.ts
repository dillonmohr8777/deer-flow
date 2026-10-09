import { expect, it } from "@rstest/core";

import {
  projectDocumentSource,
  projectDocumentTitle,
} from "@/core/projects/document-source";

it("reads a Slack channel snapshot from its file name", () => {
  const doc = { name: "slack-C0245CEKF16-360ops.md", source_thread_id: null };
  expect(projectDocumentSource(doc)).toEqual({
    kind: "slack",
    channelId: "C0245CEKF16",
    channel: "360ops",
  });
  expect(projectDocumentTitle(doc)).toBe("#360ops");
  expect(
    projectDocumentTitle({
      name: "slack-C0BV7Q7KWHX-advanced-longevity-medicine.md",
      source_thread_id: null,
    }),
  ).toBe("#advanced-longevity-medicine");
});

it("never guesses a channel for other uploads", () => {
  for (const name of [
    "00-MOMENTUM-SLACK-INDEX.md",
    "slack-notes.md",
    "slack-general.md",
    "report.pdf",
    "slack-C0245CEKF16-360ops.pdf",
  ]) {
    const doc = { name, source_thread_id: null };
    expect(projectDocumentSource(doc)).toEqual({ kind: "upload" });
    expect(projectDocumentTitle(doc)).toBe(name);
  }
});

it("prefers the recorded chat over any file-name pattern", () => {
  expect(
    projectDocumentSource({
      name: "slack-C0245CEKF16-360ops.md",
      source_thread_id: "t-1",
    }),
  ).toEqual({ kind: "thread", threadId: "t-1" });
});
