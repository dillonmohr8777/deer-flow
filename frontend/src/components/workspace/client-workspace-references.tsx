"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  listClientReferenceDocuments,
  listClientReferenceProjects,
  urlOfClientReferenceContent,
} from "@/core/client-references/api";
import { fetchScheduledTaskStatuses } from "@/core/scheduled-tasks/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";

function ReferencePage({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <main className="mx-auto w-full max-w-3xl space-y-5 p-4 sm:p-6">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {children}
    </main>
  );
}

export function ClientReferenceNavigation() {
  return (
    <nav
      aria-label="Workspace references"
      className="flex flex-col gap-2 px-4 py-2"
    >
      <Link href="/workspace/projects">Projects</Link>
      <Link href="/workspace/scheduled-tasks">Scheduled tasks</Link>
    </nav>
  );
}

export function ClientProjectList() {
  const query = useQuery({
    queryKey: ["client-reference-projects"],
    queryFn: listClientReferenceProjects,
    retry: false,
    enabled: !isStaticWebsiteOnly(),
  });
  return (
    <ReferencePage title="Projects">
      {query.isError ? (
        <p role="alert">Projects are unavailable for this account.</p>
      ) : query.isPending ? (
        <p>Loading projects…</p>
      ) : (
        <ul className="space-y-3">
          {query.data?.map((project) => (
            <li key={project.id}>
              <Link
                className="break-words underline"
                href={`/workspace/projects/${encodeURIComponent(project.id)}`}
              >
                {project.name}
              </Link>
            </li>
          ))}
          {query.data?.length === 0 && (
            <li>No projects have been shared in this workspace.</li>
          )}
        </ul>
      )}
    </ReferencePage>
  );
}

export function ClientProjectReference({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: ["client-reference-documents", projectId],
    queryFn: () => listClientReferenceDocuments(projectId),
    retry: false,
    enabled: !isStaticWebsiteOnly(),
  });
  return (
    <ReferencePage title="Project documents">
      <Link className="underline" href="/workspace/projects">
        All projects
      </Link>
      {query.isError ? (
        <p role="alert">This project is unavailable for this account.</p>
      ) : query.isPending ? (
        <p>Loading documents…</p>
      ) : (
        <>
          <ul className="space-y-3">
            {query.data?.documents.map((document) => (
              <li key={document.id} className="break-words">
                {document.content_missing ? (
                  <span>{document.name} (file unavailable)</span>
                ) : (
                  <a
                    className="underline"
                    href={urlOfClientReferenceContent(projectId, document.id)}
                  >
                    {document.name}
                  </a>
                )}
              </li>
            ))}
            {query.data?.documents.length === 0 && (
              <li>No documents have been shared in this project.</li>
            )}
          </ul>
          {query.data && query.data.total > query.data.documents.length && (
            <p>
              Showing {query.data.documents.length} of {query.data.total}{" "}
              documents. Contact your coordinator for the remaining files.
            </p>
          )}
        </>
      )}
    </ReferencePage>
  );
}

export function ClientScheduleList() {
  const query = useQuery({
    queryKey: ["client-reference-schedules"],
    queryFn: fetchScheduledTaskStatuses,
    retry: false,
    enabled: !isStaticWebsiteOnly(),
  });
  return (
    <ReferencePage title="Scheduled tasks">
      <p>
        View the tasks already set up in this workspace. Your coordinator
        manages changes.
      </p>
      {query.isError ? (
        <p role="alert">Scheduled tasks are unavailable for this account.</p>
      ) : query.isPending ? (
        <p>Loading tasks…</p>
      ) : (
        <ul className="space-y-4">
          {query.data?.map((task) => (
            <li key={task.id} className="rounded border p-3 break-words">
              <h2 className="font-medium">{task.title}</h2>
              <p>Status: {task.status}</p>
              <p>
                {task.next_run_at
                  ? `Next scheduled: ${task.next_run_at}`
                  : "No next run is recorded."}
              </p>
            </li>
          ))}
          {query.data?.length === 0 && (
            <li>No scheduled tasks are set up in this workspace.</li>
          )}
        </ul>
      )}
    </ReferencePage>
  );
}
