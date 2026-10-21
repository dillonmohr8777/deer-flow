import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { Academy } from "./types";

export const ACADEMY_QUERY_KEY = ["academy"] as const;

async function readAcademyAPIError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Fall through to the caller-provided message.
  }
  return fallback;
}

/** ``GET /api/academy`` -- the curriculum with your own progress. */
export async function getAcademy(): Promise<Academy> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}/api/academy`, {
    method: "GET",
  });
  if (!response.ok) {
    throw new Error(
      await readAcademyAPIError(response, "Failed to load the Academy."),
    );
  }
  const data = (await response.json()) as Academy;
  const base = getBackendBaseURL();
  for (const track of data.tracks) {
    for (const lesson of track.lessons) {
      for (const key of [
        "video_url",
        "video_poster_url",
        "video_captions_url",
        "video_transcript_url",
      ] as const) {
        const url = lesson[key];
        if (url?.startsWith("/")) lesson[key] = `${base}${url}`;
      }
    }
  }
  return data;
}

/** ``PUT /api/academy/lessons/{id}/progress`` -- mark or unmark a lesson. */
export async function setLessonCompleted(
  lessonId: string,
  completed: boolean,
): Promise<void> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/academy/lessons/${encodeURIComponent(lessonId)}/progress`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ completed }),
    },
  );
  if (!response.ok) {
    throw new Error(
      await readAcademyAPIError(response, "Failed to save your progress."),
    );
  }
}
