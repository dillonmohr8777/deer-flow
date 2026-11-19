import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type ClientReferenceProject = {
  id: string;
  name: string;
  status: string;
};

export type ClientReferenceDocuments = {
  documents: {
    id: string;
    name: string;
    sha256: string;
    size_bytes: number;
    content_missing: boolean;
  }[];
  total: number;
  limit: number;
  offset: number;
};

async function readReferences<T>(path: string): Promise<T> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/client-references${path}`,
    { method: "GET", cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error("References are unavailable for this account.");
  }
  return response.json() as Promise<T>;
}

export async function listClientReferenceProjects(): Promise<
  ClientReferenceProject[]
> {
  const data = await readReferences<{ projects: ClientReferenceProject[] }>(
    "/projects",
  );
  return data.projects;
}

export function listClientReferenceDocuments(
  projectId: string,
): Promise<ClientReferenceDocuments> {
  return readReferences(`/projects/${encodeURIComponent(projectId)}/documents`);
}

export function urlOfClientReferenceContent(
  projectId: string,
  documentId: string,
): string {
  return `${getBackendBaseURL()}/api/client-references/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/content?download=true`;
}
