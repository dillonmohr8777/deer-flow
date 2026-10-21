"use client";

import {
  ErrorState,
  pageStyles,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useBrandAbout } from "@/core/momobot-brand";
import { cn } from "@/lib/utils";

import styles from "./lineup.module.css";

type Block = { kind: "p"; text: string } | { kind: "ol"; items: string[] };

/** The About copy only uses paragraphs, **bold** and numbered lists. */
export function parseAbout(markdown: string): Block[] {
  const blocks: Block[] = [];
  for (const chunk of markdown.split(/\n\s*\n/)) {
    const text: string[] = [];
    const items: string[] = [];
    for (const line of chunk.split("\n")) {
      const item = /^\d+\.\s+(.*)$/.exec(line.trim());
      if (item) items.push(item[1]!);
      else if (line.trim()) text.push(line.trim());
    }
    if (text.length) blocks.push({ kind: "p", text: text.join(" ") });
    if (items.length) blocks.push({ kind: "ol", items });
  }
  return blocks;
}

function Inline({ text }: { text: string }) {
  return (
    <>
      {text
        .split("**")
        .map((part, i) =>
          i % 2 === 1 ? <strong key={i}>{part}</strong> : part,
        )}
    </>
  );
}

export function AboutContent({ markdown }: { markdown: string }) {
  return (
    <div className={cn(styles.page, styles.about)}>
      <h1>About MomoBot</h1>
      {parseAbout(markdown).map((block, i) =>
        block.kind === "p" ? (
          <p key={i}>
            <Inline text={block.text} />
          </p>
        ) : (
          <ol key={i}>
            {block.items.map((item, j) => (
              <li key={j}>
                <Inline text={item} />
              </li>
            ))}
          </ol>
        ),
      )}
    </div>
  );
}

export function AboutPanelPage() {
  const { data, isPending, isError } = useBrandAbout();
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={cn("overflow-y-auto", pageStyles.page)}>
        {isPending ? (
          <WorkingState label="Loading" className="m-8" />
        ) : isError || !data ? (
          <ErrorState
            message="Not available"
            detail="The About page is not set up on this workspace."
          />
        ) : (
          <AboutContent markdown={data.markdown} />
        )}
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
