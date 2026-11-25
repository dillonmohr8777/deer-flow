"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CheckIcon,
  CopyIcon,
  DownloadIcon,
  LoaderIcon,
  MonitorIcon,
  SmartphoneIcon,
} from "lucide-react";
import Papa from "papaparse";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { loadArtifactContent } from "@/core/artifacts/loader";
import { appendHtmlPreviewBaseHref } from "@/core/artifacts/preview";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { writeTextToClipboard } from "@/core/clipboard";
import { SafeStreamdown } from "@/core/streamdown/components";
import { getFileName } from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { artifactMarkdownPlugins } from "./markdown-preview-plugins";

export type ArtifactQuickPreviewKind =
  | "html"
  | "markdown"
  | "csv"
  | "tsv"
  | "text"
  | "json";

const MAX_TABLE_PREVIEW_ROWS = 200;

function extractNormalizedExtension(filepath: string): string {
  const withoutQuery = filepath.split(/[?#]/, 1)[0] ?? filepath;
  const lastDot = withoutQuery.lastIndexOf(".");
  if (lastDot < 0) {
    return "";
  }
  return withoutQuery.slice(lastDot + 1).toLowerCase();
}

export function getArtifactQuickPreviewKind(
  filepath: string,
): ArtifactQuickPreviewKind | null {
  const ext = extractNormalizedExtension(filepath);
  switch (ext) {
    case "html":
    case "htm":
      return "html";
    case "md":
    case "markdown":
      return "markdown";
    case "csv":
      return "csv";
    case "tsv":
      return "tsv";
    case "txt":
      return "text";
    case "json":
      return "json";
    default:
      return null;
  }
}

export function isHtmlArtifactFile(filepath: string): boolean {
  return getArtifactQuickPreviewKind(filepath) === "html";
}

export function getArtifactPreviewButtonLabel(
  kind: ArtifactQuickPreviewKind,
): string {
  return kind === "html" ? "Preview Page" : "Preview";
}

export function getArtifactPreviewSubtitle(
  kind: ArtifactQuickPreviewKind,
): string {
  switch (kind) {
    case "html":
      return "Live Page Preview";
    case "markdown":
      return "Document Preview";
    case "csv":
    case "tsv":
      return "Table Preview";
    case "json":
      return "Structured Data Preview";
    case "text":
      return "Text Preview";
  }
}

export function getCleanClientArtifactLabel(filepath: string): string {
  const kind = getArtifactQuickPreviewKind(filepath);
  if (kind === "html") {
    return "Page Ready";
  }
  if (kind !== null) {
    return "Ready to Preview";
  }
  return "File Ready";
}

export function parseDelimitedPreview(
  content: string,
  delimiter: "," | "\t",
  maxRows = MAX_TABLE_PREVIEW_ROWS,
): {
  headers: string[];
  rows: string[][];
  totalRows: number;
  truncatedRows: boolean;
} {
  const parsed = Papa.parse<string[]>(content, {
    delimiter,
    skipEmptyLines: "greedy",
  });
  const records = parsed.data.filter(
    (row) => Array.isArray(row) && row.some((cell) => cell.trim() !== ""),
  );
  if (records.length === 0) {
    return { headers: [], rows: [], totalRows: 0, truncatedRows: false };
  }
  const [first, ...rest] = records;
  const columnCount = Math.max(
    first?.length ?? 0,
    ...rest.slice(0, maxRows).map((row) => row.length),
  );
  const headers = Array.from({ length: columnCount }, (_, index) => {
    const label = first?.[index]?.trim();
    return label && label.length > 0 ? label : `Column ${index + 1}`;
  });
  const rows = rest
    .slice(0, maxRows)
    .map((row) =>
      Array.from({ length: columnCount }, (_, index) => row[index] ?? ""),
    );
  return {
    headers,
    rows,
    totalRows: rest.length,
    truncatedRows: rest.length > maxRows,
  };
}

export function formatJsonPreview(content: string): string {
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}

export function ArtifactQuickPreviewModal({
  filepath,
  threadId,
  open,
  onOpenChange,
  isMock = false,
}: {
  filepath: string | null;
  threadId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isMock?: boolean;
}) {
  const [viewport, setViewport] = useState<"desktop" | "mobile">("desktop");
  const [copied, setCopied] = useState(false);
  const [fullContent, setFullContent] = useState(false);

  useEffect(() => {
    setViewport("desktop");
    setCopied(false);
    setFullContent(false);
  }, [filepath, open]);

  const kind = filepath ? getArtifactQuickPreviewKind(filepath) : null;
  const filename = filepath ? getFileName(filepath) : "";

  const query = useQuery({
    queryKey: ["artifact", filepath, threadId, isMock, fullContent],
    queryFn: () =>
      loadArtifactContent({
        filepath: filepath!,
        threadId,
        isMock,
        full: fullContent,
      }),
    enabled: open && Boolean(filepath) && kind !== null,
    staleTime: 0,
  });

  const content = query.data?.content ?? "";
  const truncated = query.data?.truncated ?? false;
  const artifactUrl =
    query.data?.url ??
    (filepath ? urlOfArtifact({ filepath, threadId, isMock }) : undefined);

  const htmlSrcDoc = useMemo(() => {
    if (kind !== "html") {
      return "";
    }
    return appendHtmlPreviewBaseHref(content, artifactUrl);
  }, [artifactUrl, content, kind]);

  const parsedTable = useMemo(() => {
    if (kind !== "csv" && kind !== "tsv") {
      return null;
    }
    return parseDelimitedPreview(content, kind === "tsv" ? "\t" : ",");
  }, [content, kind]);

  const formattedJson = useMemo(() => {
    if (kind !== "json") {
      return "";
    }
    return formatJsonPreview(content);
  }, [content, kind]);

  const handleCopy = async () => {
    if (truncated) {
      return;
    }
    const ok = await writeTextToClipboard(content);
    if (ok) {
      setCopied(true);
      toast.success(
        kind === "html" ? "HTML copied to clipboard" : "Copied to clipboard",
      );
      setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Could not copy to clipboard");
    }
  };

  if (!filepath || !kind) {
    return null;
  }

  const downloadHref = urlOfArtifact({
    filepath,
    threadId,
    download: true,
    isMock,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex h-[85vh] max-h-[85vh] w-[95vw] max-w-5xl flex-col gap-0 overflow-hidden p-0 sm:max-w-5xl"
        data-testid="artifact-quick-preview-modal"
      >
        <DialogHeader className="border-border flex flex-row flex-wrap items-center justify-between gap-3 border-b px-4 py-3 pr-12 text-left">
          <div className="min-w-0">
            <DialogTitle className="truncate text-base">{filename}</DialogTitle>
            <DialogDescription className="text-xs">
              {getArtifactPreviewSubtitle(kind)}
            </DialogDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {kind === "html" && (
              <div
                role="group"
                aria-label="Preview viewport size"
                className="bg-muted inline-flex items-center rounded-md border p-0.5"
              >
                <Button
                  type="button"
                  size="sm"
                  variant={viewport === "desktop" ? "secondary" : "ghost"}
                  aria-pressed={viewport === "desktop"}
                  className="h-7 gap-1 px-2 text-xs"
                  onClick={() => setViewport("desktop")}
                >
                  <MonitorIcon className="size-3.5" />
                  Desktop
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={viewport === "mobile" ? "secondary" : "ghost"}
                  aria-pressed={viewport === "mobile"}
                  className="h-7 gap-1 px-2 text-xs"
                  onClick={() => setViewport("mobile")}
                >
                  <SmartphoneIcon className="size-3.5" />
                  Mobile
                </Button>
              </div>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={query.isLoading || !content || truncated}
              title={
                truncated ? "Load the full file before copying" : undefined
              }
              onClick={() => void handleCopy()}
            >
              {copied ? (
                <CheckIcon className="size-3.5" />
              ) : (
                <CopyIcon className="size-3.5" />
              )}
              {copied ? "Copied" : kind === "html" ? "Copy HTML" : "Copy"}
            </Button>
            <Button size="sm" variant="outline" asChild>
              <a href={downloadHref} target="_blank" rel="noopener noreferrer">
                <DownloadIcon className="size-3.5" />
                Download
              </a>
            </Button>
          </div>
        </DialogHeader>

        {truncated && !fullContent && (
          <div className="border-border bg-muted/60 flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2 text-xs">
            <span className="text-muted-foreground">
              Showing a preview slice of this file. Load the full file before
              copying.
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => setFullContent(true)}
            >
              Load full file
            </Button>
          </div>
        )}

        <div className="bg-muted/25 min-h-0 flex-1 overflow-auto">
          {query.isLoading ? (
            <div className="text-muted-foreground flex size-full items-center justify-center gap-2 p-6 text-sm">
              <LoaderIcon className="size-4 animate-spin" />
              <span>Loading preview...</span>
            </div>
          ) : query.isError ? (
            <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center">
              <p className="text-muted-foreground max-w-md text-sm">
                Could not load a live preview for this file. You can still
                download it directly.
              </p>
              <Button size="sm" asChild>
                <a
                  href={downloadHref}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <DownloadIcon className="size-4" />
                  Download
                </a>
              </Button>
            </div>
          ) : kind === "html" ? (
            <div
              className={cn(
                "flex size-full justify-center overflow-auto",
                viewport === "mobile" ? "p-4" : "p-0",
              )}
            >
              <iframe
                title={`Live preview of ${filename}`}
                sandbox="allow-scripts"
                srcDoc={htmlSrcDoc}
                data-testid="html-artifact-preview-iframe"
                data-viewport={viewport}
                className={cn(
                  "border-0 bg-white transition-all",
                  viewport === "mobile"
                    ? "h-full w-[390px] max-w-full rounded-xl border shadow-md"
                    : "size-full",
                )}
              />
            </div>
          ) : kind === "markdown" ? (
            <div
              className="bg-card mx-auto my-5 max-w-3xl rounded-lg border p-6 shadow-xs"
              data-testid="markdown-artifact-preview"
            >
              <SafeStreamdown className="min-w-0" {...artifactMarkdownPlugins}>
                {content}
              </SafeStreamdown>
            </div>
          ) : kind === "csv" || kind === "tsv" ? (
            <div className="p-4" data-testid="table-artifact-preview">
              {parsedTable && parsedTable.headers.length > 0 ? (
                <div className="bg-card overflow-x-auto rounded-lg border shadow-xs">
                  <div className="text-muted-foreground border-b px-3 py-2 text-xs">
                    {parsedTable.truncatedRows
                      ? `Showing first ${parsedTable.rows.length} of ${parsedTable.totalRows} rows`
                      : `${parsedTable.totalRows} ${parsedTable.totalRows === 1 ? "row" : "rows"}`}
                  </div>
                  <table className="w-full border-collapse text-left text-xs">
                    <thead className="bg-muted/50 sticky top-0">
                      <tr>
                        {parsedTable.headers.map((header, index) => (
                          <th
                            key={`${header}-${index}`}
                            className="border-b px-3 py-2 font-semibold whitespace-nowrap"
                          >
                            {header}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {parsedTable.rows.map((row, rowIndex) => (
                        <tr key={rowIndex} className="hover:bg-muted/30">
                          {row.map((cell, cellIndex) => (
                            <td
                              key={cellIndex}
                              className="max-w-xs px-3 py-2 align-top break-words"
                            >
                              {cell}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  This table file is empty.
                </p>
              )}
            </div>
          ) : kind === "json" ? (
            <pre
              className="bg-card mx-auto my-5 max-w-4xl overflow-x-auto rounded-lg border p-5 font-mono text-xs leading-relaxed whitespace-pre shadow-xs"
              data-testid="json-artifact-preview"
            >
              {formattedJson}
            </pre>
          ) : (
            <div
              className="bg-card mx-auto my-5 max-w-3xl rounded-lg border p-6 text-sm leading-relaxed whitespace-pre-wrap shadow-xs"
              data-testid="text-artifact-preview"
            >
              {content}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
