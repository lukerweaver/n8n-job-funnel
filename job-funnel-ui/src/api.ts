import type {
  JobApplicationListResponse,
  RunApplicationsResponse,
  RunListResponse,
} from "./types";

declare global {
  interface Window {
    __JOB_FUNNEL_CONFIG__?: {
      apiBaseUrl?: string;
    };
  }
}

const API_BASE_URL =
  window.__JOB_FUNNEL_CONFIG__?.apiBaseUrl ??
  import.meta.env.VITE_API_BASE_URL ??
  "http://localhost:8000";

function buildUrl(path: string, params?: URLSearchParams): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(normalizedPath, API_BASE_URL);
  if (params) {
    url.search = params.toString();
  }
  return url.toString();
}

async function fetchJson<T>(path: string, params?: URLSearchParams): Promise<T> {
  const response = await fetch(buildUrl(path, params));
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getApplications(params: URLSearchParams) {
  return fetchJson<JobApplicationListResponse>("/applications", params);
}

export function getRuns(params: URLSearchParams) {
  return fetchJson<RunListResponse>("/runs", params);
}

export function getRunApplications(runId: string, params: URLSearchParams) {
  return fetchJson<RunApplicationsResponse>(`/runs/${runId}/applications`, params);
}
