"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { fetch as apiFetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { listProjects } from "@/core/projects/api";

export function WorkProjectPicker({
  userId,
  workspace,
  clientId,
  requestId,
  workChatId,
  workRunId,
  disabled,
  onStart,
}: {
  userId: string;
  workspace: string;
  clientId: string;
  requestId: string;
  workChatId?: string;
  workRunId?: string;
  disabled: boolean;
  onStart: (projectId: string | null) => void;
}) {
  const [choice, setChoice] = useState<string | null>();
  const key = ["portal", userId, workspace];
  const projects = useQuery({
    queryKey: [...key, "projects", clientId, requestId],
    queryFn: ({ signal }) => listProjects("active", { signal }),
    gcTime: 0,
    retry: false,
  });
  const binding = useQuery({
    queryKey: [...key, "work-project", requestId, workChatId, workRunId],
    enabled: Boolean(workChatId),
    queryFn: async ({ signal }) => {
      const response = await apiFetch(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(workChatId!)}`,
        { signal, cache: "no-store" },
      );
      if (!response.ok) {
        throw new Error(
          "Saved work project is unavailable. Refresh and retry.",
        );
      }
      const thread = (await response.json()) as {
        thread_id: string;
        metadata?: Record<string, unknown> | null;
      };
      const project = thread.metadata?.deerflow_project_id;
      if (
        thread.thread_id !== workChatId ||
        (project != null && (typeof project !== "string" || !project))
      ) {
        throw new Error("Saved work project does not match this conversation.");
      }
      return typeof project === "string" ? project : null;
    },
    gcTime: 0,
    retry: false,
  });
  const available = projects.data?.filter(
    (project) => project.status === "active" && project.client_id === clientId,
  );
  const uncertain = Boolean(
    (Boolean(workChatId) && (binding.isPending || binding.isError)) ||
    (Boolean(workRunId) && !workChatId),
  );
  const frozen = Boolean(workRunId) || Boolean(binding.data);
  const projectId = frozen ? (binding.data ?? null) : choice;
  const valid =
    projectId === null ||
    available?.some((project) => project.id === projectId);
  const projectName = binding.data
    ? (available?.find((project) => project.id === binding.data)?.name ??
      `Project ${binding.data}`)
    : "No project";

  return (
    <section
      aria-label="Work project selection"
      className="mb-4 min-w-0 space-y-2"
    >
      {uncertain ? (
        <p role={binding.isError || !workChatId ? "alert" : "status"}>
          {binding.error?.message ??
            (workChatId
              ? "Checking saved work project…"
              : "Saved work project is unavailable. Refresh and retry.")}
        </p>
      ) : frozen ? (
        <p className="break-words" role="status">
          Work project: {projectName}. Selection is fixed for this request.
        </p>
      ) : (
        <label className="block space-y-1">
          <span>Work project</span>
          <select
            aria-label="Work project"
            className="bg-background min-h-11 w-full rounded border p-2"
            value={
              choice === undefined
                ? "choose"
                : choice === null
                  ? "none"
                  : `project:${choice}`
            }
            disabled={disabled}
            onChange={(event) =>
              setChoice(
                event.target.value === "none"
                  ? null
                  : event.target.value.slice(8),
              )
            }
          >
            <option value="choose" disabled>
              Choose a project or no project
            </option>
            <option value="none">No project</option>
            {available?.map((project) => (
              <option key={project.id} value={`project:${project.id}`}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {!frozen && projects.isPending && (
        <p role="status">Loading client projects…</p>
      )}
      {!frozen && projects.isError && (
        <p role="alert">{projects.error.message}</p>
      )}
      <Button
        variant="outline"
        className="min-h-11"
        disabled={disabled || uncertain || (!frozen && !valid)}
        onClick={() => onStart(projectId ?? null)}
      >
        {workRunId ? "Resume Momo work" : "Ask Momo to work"}
      </Button>
    </section>
  );
}
