"use client";

import { FolderIcon, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatArtifactBytes } from "@/components/workspace/artifacts/artifact-file-preview";
import {
  EmptyState,
  ErrorState,
  pageStyles,
  StatusTag,
  WorkingState,
} from "@/components/workspace/page-body";
import { useI18n } from "@/core/i18n/hooks";
import {
  PROJECTS_CONFIG_DEFAULT,
  useProjects,
  useProjectsConfig,
} from "@/core/projects";
import {
  RestoreConflictError,
  TrashNotFoundError,
  useEmptyTrash,
  useInfiniteTrashDocuments,
  usePurgeDocument,
  useRestoreDocument,
  type TrashDocument,
} from "@/core/trash";
import { getFileIcon } from "@/core/utils/files";
import { cn } from "@/lib/utils";

function errorToastMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Remaining whole days of the retention window (spec §8.3); the effective
 * window comes from ``GET /api/projects/config`` — expired rows are swept
 * server-side. */
export function retentionDaysLeft(
  trashedAt: string,
  retentionDays: number,
  now = Date.now(),
): number {
  const expiresAt = new Date(trashedAt).getTime() + retentionDays * 86_400_000;
  const left = expiresAt - now;
  // Under a day is "Less than a day left" (0), not a rounded-up "1 day".
  return left < 86_400_000 ? 0 : Math.ceil(left / 86_400_000);
}

/** Days left at or under which a row says so as an attention tag: the
 * document is about to be deleted for good. */
export const RETENTION_ATTENTION_DAYS = 3;

/**
 * Trash view (spec §9): trashed shelf documents with their origin project
 * and remaining retention, per-entry Restore / Delete-permanently behind an
 * irreversible confirmation, and "Empty trash" with its own confirmation.
 */
export function TrashView() {
  const { t } = useI18n();
  const trashQuery = useInfiniteTrashDocuments();
  const configQuery = useProjectsConfig();
  const retentionDays =
    configQuery.data?.trash_retention_days ??
    PROJECTS_CONFIG_DEFAULT.trash_retention_days;
  const documents =
    trashQuery.data?.pages.flatMap((page) => page.documents) ?? [];
  const documentsTotal = trashQuery.data?.pages.at(-1)?.total ?? 0;
  const [purgeTarget, setPurgeTarget] = useState<TrashDocument | null>(null);
  const [emptyConfirmOpen, setEmptyConfirmOpen] = useState(false);
  const emptyTrash = useEmptyTrash();

  return (
    <div className="mx-auto flex w-full max-w-(--container-width-lg) flex-col gap-6 p-4 pt-8 pb-28 sm:p-6 sm:pt-10 sm:pb-28">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 basis-72">
          <h1 className="text-2xl font-semibold">{t.trash.title}</h1>
          <p className={cn(pageStyles.lede, "mt-1")}>
            {t.trash.retentionNote(retentionDays)}
          </p>
        </div>
        {documents.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="text-destructive hover:text-destructive max-sm:h-11"
            onClick={() => setEmptyConfirmOpen(true)}
            data-testid="trash-empty-button"
          >
            <Trash2 className="size-4" />
            {t.trash.emptyTrash}
          </Button>
        )}
      </header>

      {trashQuery.isError ? (
        <ErrorState
          message={t.trash.loadFailed}
          action={
            <Button
              variant="outline"
              size="sm"
              className="max-sm:h-11"
              onClick={() => void trashQuery.refetch()}
            >
              {t.trash.retry}
            </Button>
          }
        />
      ) : trashQuery.isLoading ? (
        <WorkingState label={t.common.loading} />
      ) : documents.length === 0 ? (
        <EmptyState momo="builder" title={t.trash.empty}>
          {t.trash.emptyHint}
        </EmptyState>
      ) : (
        <>
          {/* Phones: each document is a paper slip on the desk, as Agents,
              Chats and Scheduled tasks are. */}
          <ul
            className={cn(
              "flex w-full flex-col divide-y border-y",
              pageStyles.rows,
              pageStyles.slips,
            )}
          >
            {documents.map((document) => (
              <TrashDocumentRow
                key={document.id}
                document={document}
                retentionDays={retentionDays}
                onPurge={() => setPurgeTarget(document)}
              />
            ))}
          </ul>
          <div className="flex flex-col items-center gap-1">
            <p
              className={cn(pageStyles.figure, "text-muted-foreground text-xs")}
            >
              {t.common.showingOf(documents.length, documentsTotal)}
            </p>
            {trashQuery.hasNextPage && (
              <Button
                variant="ghost"
                size="sm"
                className="text-xs max-sm:min-h-11"
                disabled={trashQuery.isFetchingNextPage}
                onClick={() => void trashQuery.fetchNextPage()}
                data-testid="trash-load-more"
              >
                {trashQuery.isFetchingNextPage
                  ? t.chats.loadingMore
                  : t.common.loadMore}
              </Button>
            )}
          </div>
        </>
      )}

      <Dialog
        open={purgeTarget !== null}
        onOpenChange={(open) => !open && setPurgeTarget(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.trash.deletePermanentlyTitle}</DialogTitle>
            <DialogDescription>
              {purgeTarget &&
                t.trash.deletePermanentlyConfirm(purgeTarget.name)}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPurgeTarget(null)}>
              {t.common.cancel}
            </Button>
            <PurgeConfirmButton
              target={purgeTarget}
              onDone={() => setPurgeTarget(null)}
            />
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={emptyConfirmOpen} onOpenChange={setEmptyConfirmOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.trash.emptyTrashTitle}</DialogTitle>
            <DialogDescription>
              {t.trash.emptyTrashConfirm(documentsTotal)}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEmptyConfirmOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              disabled={emptyTrash.isPending}
              onClick={() =>
                emptyTrash.mutate(undefined, {
                  onSuccess: () => setEmptyConfirmOpen(false),
                  onError: (error) => {
                    toast.error(
                      errorToastMessage(error, t.trash.emptyTrashFailed),
                    );
                  },
                })
              }
            >
              {t.trash.emptyTrash}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PurgeConfirmButton({
  target,
  onDone,
}: {
  target: TrashDocument | null;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const purgeDocument = usePurgeDocument();
  return (
    <Button
      variant="destructive"
      disabled={purgeDocument.isPending || target === null}
      onClick={() => {
        if (!target) {
          return;
        }
        purgeDocument.mutate(target.id, {
          onSuccess: onDone,
          onError: (error) => {
            toast.error(errorToastMessage(error, t.trash.purgeFailed));
          },
        });
      }}
    >
      {t.trash.deletePermanently}
    </Button>
  );
}

function TrashDocumentRow({
  document,
  retentionDays,
  onPurge,
}: {
  document: TrashDocument;
  retentionDays: number;
  onPurge: () => void;
}) {
  const { t } = useI18n();
  const restoreDocument = useRestoreDocument();
  // Set when a targetless restore 404s: the origin project is gone or
  // archived, so the row offers the active-project picker (§8.2, §11).
  const [pickerOpen, setPickerOpen] = useState(false);

  const restore = (projectId?: string) => {
    restoreDocument.mutate(
      { documentId: document.id, projectId },
      {
        onSuccess: (result) => {
          toast.success(
            result.outcome === "merged"
              ? t.trash.restoreMergedToast(result.document.name)
              : t.trash.restoredToast(result.document.name),
          );
          setPickerOpen(false);
        },
        onError: (error) => {
          if (error instanceof RestoreConflictError) {
            // 409 content_missing: the bytes are gone; the row stays.
            toast.error(t.trash.restoreConflict);
            return;
          }
          if (error instanceof TrashNotFoundError && projectId === undefined) {
            setPickerOpen(true);
            return;
          }
          toast.error(errorToastMessage(error, t.trash.restoreFailed));
        },
      },
    );
  };

  const daysLeft = retentionDaysLeft(document.trashed_at, retentionDays);
  const projectName = document.trash_origin?.project_name;
  const retention =
    daysLeft <= RETENTION_ATTENTION_DAYS ? (
      <StatusTag tone="attention">{t.trash.retentionLeft(daysLeft)}</StatusTag>
    ) : (
      <span>{t.trash.retentionLeft(daysLeft)}</span>
    );

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 max-sm:px-4 max-sm:py-3.5">
      <span className="text-muted-foreground shrink-0 self-start pt-0.5">
        {getFileIcon(document.name, "size-5")}
      </span>
      <div className="flex min-w-0 flex-1 basis-48 flex-col gap-0.5">
        {/* The name is the document: up to two lines, never cut mid-word
            to one line of a long file name. */}
        <span
          className="line-clamp-2 text-sm font-bold [overflow-wrap:anywhere]"
          title={document.name}
        >
          {document.name}
        </span>
        <span className="text-muted-foreground flex flex-wrap items-center gap-x-1.5 text-xs">
          <span>
            {projectName
              ? t.trash.originProject(projectName)
              : t.trash.unknownProject}
          </span>
          <span aria-hidden="true">·</span>
          <span className={pageStyles.figure}>
            {formatArtifactBytes(document.size_bytes)}
          </span>
        </span>
      </div>
      {/* Time left stands beside the actions it argues for. On phones this
          is the slip's foot line, time left on the left and the actions at
          44px on the right, as Desk slips read; the irreversible delete is
          an icon there, still behind its confirmation. */}
      <div className="flex shrink-0 items-center gap-1 max-sm:basis-full max-sm:pl-8">
        <span className="text-muted-foreground mr-auto text-xs sm:mr-3">
          {retention}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="max-sm:h-11 max-sm:px-4"
          disabled={restoreDocument.isPending}
          onClick={() => restore()}
        >
          <RotateCcw className="size-4" />
          {t.trash.restore}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive max-sm:size-11 max-sm:p-0"
          onClick={onPurge}
          title={t.trash.deletePermanently}
        >
          <Trash2 className="size-4" />
          <span className="max-sm:sr-only">{t.trash.deletePermanently}</span>
        </Button>
      </div>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.trash.restorePickProjectTitle}</DialogTitle>
            <DialogDescription>
              {t.trash.restorePickProjectHint}
            </DialogDescription>
          </DialogHeader>
          <RestoreProjectPicker
            isPending={restoreDocument.isPending}
            onPick={(projectId) => restore(projectId)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPickerOpen(false)}>
              {t.common.cancel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}

function RestoreProjectPicker({
  isPending,
  onPick,
}: {
  isPending: boolean;
  onPick: (projectId: string) => void;
}) {
  const { t } = useI18n();
  const projectsQuery = useProjects("active");
  const projects = projectsQuery.data ?? [];
  if (projectsQuery.isLoading) {
    return <WorkingState label={t.common.loading} />;
  }
  if (projects.length === 0) {
    return (
      <p className="text-muted-foreground p-2 text-sm">{t.projects.empty}</p>
    );
  }
  return (
    // A ruled list of the places it can go, so each name reads as a choice.
    <ul className="flex max-h-80 flex-col divide-y overflow-auto border-y">
      {projects.map((project) => (
        <li key={project.id}>
          <Button
            variant="ghost"
            className="h-11 w-full justify-start rounded-none"
            disabled={isPending}
            onClick={() => onPick(project.id)}
          >
            <FolderIcon className="text-muted-foreground size-4" />
            <span className="truncate">{project.name}</span>
          </Button>
        </li>
      ))}
    </ul>
  );
}
