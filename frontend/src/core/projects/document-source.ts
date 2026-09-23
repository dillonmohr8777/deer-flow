import type { ProjectDocument } from "./types";

/**
 * Slack channel snapshots are uploaded as `slack-<channel id>-<channel>.<ext>`
 * (the Momentum knowledge import). The file name is the only record of the
 * channel, so this reads it from there and nowhere else.
 */
const SLACK_EXPORT = /^slack-(C[A-Z0-9]{6,})-(.+)\.(md|markdown|txt|json)$/i;

export type ProjectDocumentSource =
  | { kind: "thread"; threadId: string }
  | { kind: "slack"; channel: string; channelId: string }
  | { kind: "upload" };

/** Where a shelf document came from, for the Source column. */
export function projectDocumentSource(
  document: Pick<ProjectDocument, "name" | "source_thread_id">,
): ProjectDocumentSource {
  if (document.source_thread_id) {
    return { kind: "thread", threadId: document.source_thread_id };
  }
  const slack = SLACK_EXPORT.exec(document.name);
  if (slack) {
    return {
      kind: "slack",
      channelId: slack[1]!.toUpperCase(),
      channel: slack[2]!,
    };
  }
  return { kind: "upload" };
}

/** Title to scan by: `#channel` for a Slack snapshot, else the file name. */
export function projectDocumentTitle(
  document: Pick<ProjectDocument, "name" | "source_thread_id">,
): string {
  const source = projectDocumentSource(document);
  return source.kind === "slack" ? `#${source.channel}` : document.name;
}
