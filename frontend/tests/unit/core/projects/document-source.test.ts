import { expect, it } from "@rstest/core";

import {
  projectDocumentSource,
  projectDocumentTitle,
} from "@/core/projects/document-source";

it("reads a Slack channel snapshot from its file name", () => {
  const doc = { name: "slack-C000TEST01-ops-room.md", source_thread_id: null };
  expect(projectDocumentSource(doc)).toEqual({
    kind: "slack",
    channelId: "C000TEST01",
    channel: "ops-room",
  });
  expect(projectDocumentTitle(doc)).toBe("#ops-room");
  expect(
    projectDocumentTitle({
      name: "slack-C000TEST02-acme-wellness-clinic.md",
      source_thread_id: null,
    }),
  ).toBe("#acme-wellness-clinic");
});

it("never guesses a channel for other uploads", () => {
  for (const name of [
    "00-MOMENTUM-SLACK-INDEX.md",
    "slack-notes.md",
    "slack-general.md",
    "report.pdf",
    "slack-C000TEST01-ops-room.pdf",
  ]) {
    const doc = { name, source_thread_id: null };
    expect(projectDocumentSource(doc)).toEqual({ kind: "upload" });
    expect(projectDocumentTitle(doc)).toBe(name);
  }
});

it("prefers the recorded chat over any file-name pattern", () => {
  expect(
    projectDocumentSource({
      name: "slack-C000TEST01-ops-room.md",
      source_thread_id: "t-1",
    }),
  ).toEqual({ kind: "thread", threadId: "t-1" });
});
