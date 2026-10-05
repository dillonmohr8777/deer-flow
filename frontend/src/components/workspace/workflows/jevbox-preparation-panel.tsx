"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  getJevboxPreparationStatus,
  getWorkflowWorkspaceProjection,
  prepareJevboxEvidence,
  isWorkflowScopeError,
} from "@/core/workflows/api";
import {
  JEVBOX_MAX_PACKET_BYTES,
  type JevboxPreparationStatus,
  type JevboxProposalPreview,
} from "@/core/workflows/jevbox-preparation";

export function JevboxPreparationPane({ owner }: { owner: string }) {
  const queryClient = useQueryClient();
  const workspace = useQuery({
    queryKey: ["workflows", owner, "workspace-projection"],
    queryFn: ({ signal }) => getWorkflowWorkspaceProjection(signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
  const workspaceId = workspace.data?.activeWorkspaceId ?? null;
  const status = useQuery({
    queryKey: [
      "workflows",
      owner,
      "jevbox-preparation",
      workspaceId ?? "private",
    ],
    queryFn: ({ signal }) => getJevboxPreparationStatus(owner, signal),
    enabled: workspace.isSuccess,
    retry: false,
    staleTime: 0,
  });
  useEffect(() => {
    const key = [
      "workflows",
      owner,
      "jevbox-preparation",
      workspaceId ?? "private",
    ];
    return () => {
      void queryClient.cancelQueries({ queryKey: key, exact: true });
      queryClient.removeQueries({ queryKey: key, exact: true });
    };
  }, [queryClient, owner, workspaceId]);

  return (
    <JevboxPreparationPanel
      key={`${owner}:${workspaceId ?? "private"}:${status.data?.owner_scope ?? "pending"}:${status.data?.preparation_available ?? false}:${status.data?.current_review ?? false}:${status.errorUpdatedAt}:${workspace.errorUpdatedAt}`}
      owner={owner}
      workspaceId={workspaceId}
      status={status.data ?? null}
      loading={workspace.isLoading || status.isLoading}
      failed={!!workspace.error || !!status.error}
      onRefresh={async () => {
        const next = await workspace.refetch();
        if (next.data)
          await queryClient.invalidateQueries({
            queryKey: ["workflows", owner, "jevbox-preparation"],
          });
      }}
    />
  );
}

function JevboxPreparationPanel({
  owner,
  workspaceId,
  status,
  loading,
  failed,
  onRefresh,
}: {
  owner: string;
  workspaceId: string | null;
  status: JevboxPreparationStatus | null;
  loading: boolean;
  failed: boolean;
  onRefresh: () => Promise<void>;
}) {
  const { t } = useI18n();
  const copy = t.workflowPreparation;
  const fileInput = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<JevboxProposalPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bindFileInput = useCallback((input: HTMLInputElement | null) => {
    if (fileInput.current && fileInput.current !== input)
      fileInput.current.value = "";
    fileInput.current = input;
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      controller.current?.abort();
      controller.current = null;
    };
  }, []);

  const reset = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    setFile(null);
    setPreview(null);
    setError(null);
    setBusy(false);
    if (fileInput.current) fileInput.current.value = "";
  }, []);

  useEffect(() => {
    if (
      failed ||
      (status !== null &&
        (!status.preparation_available || !status.current_review))
    )
      reset();
  }, [failed, reset, status]);

  function onFileChange(next: File | null) {
    setPreview(null);
    setError(null);
    if (!next) {
      setFile(null);
      return;
    }
    if (!next.size || next.size > JEVBOX_MAX_PACKET_BYTES) {
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setError(copy.fileSizeInvalid);
      return;
    }
    setFile(next);
  }

  async function prepare() {
    if (
      !file ||
      failed ||
      !status?.preparation_available ||
      !status.current_review ||
      busy
    )
      return;
    controller.current?.abort();
    const requestController = new AbortController();
    controller.current = requestController;
    const requestGeneration = ++generation.current;
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      const proposal = await prepareJevboxEvidence(
        file,
        status.owner_scope,
        { ownerId: owner, workspaceId },
        requestController.signal,
      );
      if (
        mounted.current &&
        !requestController.signal.aborted &&
        requestGeneration === generation.current
      ) {
        setPreview(proposal);
        setFile(null);
        if (fileInput.current) fileInput.current.value = "";
      }
    } catch (cause) {
      if (requestController.signal.aborted || !mounted.current) return;
      if (isWorkflowScopeError(cause)) {
        reset();
        setError(copy.scopeChanged);
        void onRefresh();
      } else if (
        cause instanceof Error &&
        "status" in cause &&
        (cause.status === 409 || cause.message === "review_not_current")
      ) {
        reset();
        setError(copy.reviewExpired);
        void onRefresh();
      } else {
        setError(copy.failed);
      }
    } finally {
      if (mounted.current && requestGeneration === generation.current) {
        setBusy(false);
        if (controller.current === requestController) controller.current = null;
      }
    }
  }

  return (
    <section
      aria-labelledby="jevbox-preparation-title"
      className="mx-4 my-5 min-w-0 space-y-4 rounded-lg border p-4 md:mx-6 md:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 id="jevbox-preparation-title" className="text-lg font-semibold">
            {copy.title}
          </h2>
          <p className="text-muted-foreground text-sm">{copy.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            onClick={() => void onRefresh()}
            disabled={loading || busy}
          >
            {copy.refresh}
          </Button>
          <span className="rounded border px-2 py-1 text-xs font-medium">
            {copy.tag}
          </span>
        </div>
      </div>
      {loading && (
        <p role="status" className="text-sm">
          {copy.checking}
        </p>
      )}
      {failed && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm">
            {copy.statusFailed}
          </p>
          <Button
            type="button"
            variant="outline"
            className="min-h-11"
            onClick={() => void onRefresh()}
          >
            {copy.refresh}
          </Button>
        </div>
      )}
      {!loading && !failed && !status?.preparation_available && (
        <p role="status" className="text-sm">
          {copy.unavailable}
        </p>
      )}
      {!loading &&
        !failed &&
        status?.preparation_available &&
        !status.current_review && (
          <p role="status" className="text-sm">
            {copy.expired}
          </p>
        )}
      {!loading &&
        !failed &&
        status?.preparation_available &&
        status.current_review && (
          <div className="space-y-3">
            <p className="text-sm">{copy.uploadHint}</p>
            <label
              htmlFor="jevbox-reviewed-file"
              className="block text-sm font-medium"
            >
              {copy.fileLabel}
            </label>
            <input
              ref={bindFileInput}
              id="jevbox-reviewed-file"
              type="file"
              accept=".json,application/json"
              className="border-input bg-background file:bg-muted min-h-11 w-full min-w-0 rounded-md border p-2 text-sm file:mr-3 file:min-h-8 file:rounded file:border-0 file:px-3"
              onChange={(event) =>
                onFileChange(event.currentTarget.files?.[0] ?? null)
              }
              disabled={busy || failed || !status.current_review}
            />
            {file && (
              <p className="text-muted-foreground text-xs break-all">
                {copy.selectedFile(file.name, file.size)}
              </p>
            )}
            {error && (
              <p role="alert" className="text-sm">
                {error}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                className="min-h-11"
                onClick={() => void prepare()}
                disabled={!file || busy || failed || !status.current_review}
              >
                {busy ? copy.preparing : copy.prepare}
              </Button>
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                onClick={reset}
                disabled={busy && !controller.current}
              >
                {copy.clear}
              </Button>
            </div>
            <p className="text-muted-foreground text-xs">{copy.limitations}</p>
          </div>
        )}
      {preview &&
        !failed &&
        status?.preparation_available &&
        status.current_review && (
          <div className="space-y-3 border-t pt-4">
            <p className="text-sm font-semibold">
              {copy.unsent} ·{" "}
              {preview.evidenceMode === "synthetic"
                ? copy.synthetic
                : copy.reviewed}
            </p>
            <PreviewField label={copy.brief} value={preview.brief} />
            <PreviewField
              label={copy.question}
              value={preview.researchQuestion}
            />
            <PreviewField label={copy.sources} value={preview.sourceExcerpts} />
            <PreviewField
              label={copy.context}
              value={preview.knowledgeContext}
            />
            <p className="text-muted-foreground text-xs">{copy.sourceReview}</p>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              onClick={reset}
            >
              {copy.clear}
            </Button>
          </div>
        )}
    </section>
  );
}

function PreviewField({ label, value }: { label: string; value: string }) {
  return (
    <section className="min-w-0 space-y-1">
      <h3 className="text-sm font-medium">{label}</h3>
      <pre className="bg-muted max-h-64 min-w-0 overflow-auto rounded-md p-3 text-xs leading-relaxed break-words whitespace-pre-wrap">
        {value}
      </pre>
    </section>
  );
}
