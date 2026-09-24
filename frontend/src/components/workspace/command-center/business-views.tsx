"use client";

import { AlertCircle, FileText, FolderKanban, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { resolveArtifactOpenURL } from "@/core/artifacts/viewer";
import { useClients } from "@/core/clients";
import { useInfiniteProjectThreadFiles, useProjects } from "@/core/projects";
import { useScheduledTasks } from "@/core/scheduled-tasks/hooks";
import { pathOfThread } from "@/core/threads/utils";

import styles from "./business-views.module.css";

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatDate(value: string | null | undefined) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : dateFormatter.format(date);
}

function QueryNotice({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className={styles.notice} role="alert">
      <AlertCircle size={18} aria-hidden="true" />
      <span>{message}</span>
      <button type="button" onClick={onRetry} className={styles.linkButton}>
        <RefreshCw size={14} aria-hidden="true" /> Retry
      </button>
    </div>
  );
}

export function WorkflowsView() {
  const query = useScheduledTasks();
  const tasks = query.data ?? [];
  return (
    <section className={styles.view} aria-labelledby="workflows-heading">
      <div className={styles.header}>
        <div>
          <h2 id="workflows-heading">Workflows</h2>
          <p className={styles.subtle}>
            Scheduled definitions and their current state.
          </p>
        </div>
        <Link className={styles.action} href="/workspace/scheduled-tasks">
          Open scheduler
        </Link>
      </div>
      {query.isLoading ? (
        <p className={styles.state}>Loading workflows…</p>
      ) : null}
      {query.isError ? (
        <QueryNotice
          message="Workflows could not be loaded."
          onRetry={() => void query.refetch()}
        />
      ) : null}
      {!query.isLoading && !query.isError && tasks.length === 0 ? (
        <p className={styles.state}>No scheduled workflows yet.</p>
      ) : null}
      {tasks.length > 0 ? (
        <div className={styles.tableWrap}>
          <table>
            <caption className={styles.srOnly}>Scheduled workflows</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Status</th>
                <th scope="col">Next run</th>
                <th scope="col">Last run</th>
                <th scope="col">
                  <span className={styles.srOnly}>Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id}>
                  <td>
                    <strong>{task.title || "Untitled workflow"}</strong>
                    <span className={styles.meta}>
                      {task.schedule_type || "Schedule not reported"}
                    </span>
                  </td>
                  <td>
                    <span className={styles.status} data-status={task.status}>
                      {task.status || "Status not reported"}
                    </span>
                  </td>
                  <td>
                    {task.next_run_at
                      ? formatDate(task.next_run_at)
                      : "Not scheduled"}
                  </td>
                  <td>
                    {task.last_run_at
                      ? formatDate(task.last_run_at)
                      : "No runs recorded"}
                  </td>
                  <td>
                    <Link
                      className={styles.textLink}
                      href="/workspace/scheduled-tasks"
                    >
                      View scheduler
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function ClientSpacesView() {
  const query = useClients();
  const clients = query.data ?? [];
  return (
    <section className={styles.view} aria-labelledby="client-spaces-heading">
      <div className={styles.header}>
        <div>
          <h2 id="client-spaces-heading">Client spaces</h2>
          <p className={styles.subtle}>Clients your workspace manages.</p>
        </div>
      </div>
      {query.isLoading ? (
        <p className={styles.state}>Loading clients…</p>
      ) : null}
      {query.isError ? (
        <QueryNotice
          message="Clients could not be loaded."
          onRetry={() => void query.refetch()}
        />
      ) : null}
      {!query.isLoading && !query.isError && clients.length === 0 ? (
        <p className={styles.state}>
          No clients yet. Clients you create appear here.
        </p>
      ) : null}
      <ul className={styles.cards}>
        {clients.map((client) => (
          <li key={client.id} className={styles.card}>
            <FolderKanban size={20} aria-hidden="true" />
            <div>
              <strong>{client.display_name}</strong>
              <span className={styles.meta}>
                {client.status} · {client.assignments.length} assigned ·{" "}
                {client.project_count} project
                {client.project_count === 1 ? "" : "s"}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ArtifactLibraryView() {
  const projectsQuery = useProjects("active");
  const [projectId, setProjectId] = useState("");
  const project = projectsQuery.data?.find((item) => item.id === projectId);
  const filesQuery = useInfiniteProjectThreadFiles(
    projectId,
    { thread_limit: 20, file_limit: 20 },
    { enabled: Boolean(project) },
  );
  const groups = filesQuery.data?.pages.flatMap((page) => page.groups) ?? [];
  return (
    <section className={styles.view} aria-labelledby="artifact-library-heading">
      <div className={styles.header}>
        <div>
          <h2 id="artifact-library-heading">Artifact library</h2>
          <p className={styles.subtle}>
            Files from the conversations in one project.
          </p>
        </div>
      </div>
      {projectsQuery.isError ? (
        <QueryNotice
          message="Projects could not be loaded."
          onRetry={() => void projectsQuery.refetch()}
        />
      ) : null}
      <label className={styles.selectLabel} htmlFor="artifact-project">
        Project
      </label>
      <select
        id="artifact-project"
        value={projectId}
        onChange={(event) => setProjectId(event.target.value)}
        disabled={projectsQuery.isLoading || projectsQuery.isError}
      >
        <option value="">Select a project…</option>
        {(projectsQuery.data ?? []).map((item) => (
          <option value={item.id} key={item.id}>
            {item.name}
          </option>
        ))}
      </select>
      {!projectId ? (
        <p className={styles.state}>
          {projectsQuery.data?.length === 0
            ? "No active projects yet, so there are no files to list."
            : "Choose a project to load its thread files."}
        </p>
      ) : null}
      {project && filesQuery.isLoading ? (
        <p className={styles.state}>Loading artifacts…</p>
      ) : null}
      {project && filesQuery.isError ? (
        <QueryNotice
          message="Artifacts could not be loaded."
          onRetry={() => void filesQuery.refetch()}
        />
      ) : null}
      {project &&
      !filesQuery.isLoading &&
      !filesQuery.isError &&
      groups.length === 0 ? (
        <p className={styles.state}>No thread files in this project.</p>
      ) : null}
      <div className={styles.groups}>
        {groups.map((group) => (
          <article key={group.thread_id} className={styles.group}>
            <div className={styles.groupHeader}>
              <strong>{group.display_name || "Untitled thread"}</strong>
              <Link
                href={pathOfThread(group.thread_id)}
                className={styles.textLink}
              >
                Open thread
              </Link>
            </div>
            <ul>
              {group.files.map((file) => {
                const path = `/mnt/user-data/${file.kind === "upload" ? "uploads" : "outputs"}/${file.name}`;
                return (
                  <li key={`${file.kind}:${file.name}`} className={styles.file}>
                    <FileText size={16} aria-hidden="true" />
                    <span className={styles.fileName}>{file.name}</span>
                    <span className={styles.meta}>
                      {formatDate(file.modified_at)}
                    </span>
                    <a
                      className={styles.textLink}
                      href={resolveArtifactOpenURL({
                        filepath: path,
                        threadId: group.thread_id,
                      })}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Preview
                    </a>
                  </li>
                );
              })}
            </ul>
            {group.truncated ? (
              <p className={styles.truncated}>
                Showing the first 20 files for this thread. Open the thread for
                the full view.
              </p>
            ) : null}
          </article>
        ))}
      </div>
      {filesQuery.hasNextPage ? (
        <button
          type="button"
          className={styles.loadMore}
          disabled={filesQuery.isFetchingNextPage}
          onClick={() => void filesQuery.fetchNextPage()}
        >
          {filesQuery.isFetchingNextPage ? "Loading…" : "Load more threads"}
        </button>
      ) : null}
      {!project && projectId ? (
        <p className={styles.state}>
          That project is no longer in the active project list.
        </p>
      ) : null}
    </section>
  );
}
