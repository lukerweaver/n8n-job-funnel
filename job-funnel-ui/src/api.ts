import type {
  InterviewRound,
  InterviewRoundListResponse,
  JobApplicationListResponse,
  JobApplication,
  JobIngestResponse,
  PromptLibrary,
  PromptLibraryListResponse,
  Resume,
  ResumeListResponse,
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

async function sendJson<T>(path: string, method: "POST" | "PUT" | "DELETE", body?: unknown): Promise<T> {
  const response = await fetch(buildUrl(path), {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with status ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export function getApplications(params: URLSearchParams) {
  return fetchJson<JobApplicationListResponse>("/applications", params);
}

export function getApplication(applicationId: number) {
  return fetchJson<JobApplication>(`/applications/${applicationId}`);
}

export function updateApplicationStatus(
  applicationId: number,
  payload: {
    status: string;
    applied_at?: string | null;
    offer_at?: string | null;
    rejected_at?: string | null;
    ghosted_at?: string | null;
    withdrawn_at?: string | null;
    passed_at?: string | null;
  },
) {
  return sendJson<JobApplication>(`/applications/${applicationId}/status`, "POST", payload);
}

export function getInterviewRounds(applicationId: number) {
  return fetchJson<InterviewRoundListResponse>(`/applications/${applicationId}/interview-rounds`);
}

export function createInterviewRound(
  applicationId: number,
  payload: {
    round_number: number;
    stage_name?: string | null;
    status?: "scheduled" | "completed";
    notes?: string | null;
    scheduled_at?: string | null;
    completed_at?: string | null;
  },
) {
  return sendJson<InterviewRound>(`/applications/${applicationId}/interview-rounds`, "POST", payload);
}

export function updateInterviewRound(
  applicationId: number,
  interviewRoundId: number,
  payload: {
    round_number?: number | null;
    stage_name?: string | null;
    status?: "scheduled" | "completed" | null;
    notes?: string | null;
    scheduled_at?: string | null;
    completed_at?: string | null;
  },
) {
  return sendJson<InterviewRound>(`/applications/${applicationId}/interview-rounds/${interviewRoundId}`, "PUT", payload);
}

export function deleteInterviewRound(applicationId: number, interviewRoundId: number) {
  return sendJson<{ deleted: boolean; id: number }>(
    `/applications/${applicationId}/interview-rounds/${interviewRoundId}`,
    "DELETE",
  );
}

export function createJobDescription(payload: {
  job_id: string;
  company_name?: string | null;
  title?: string | null;
  apply_url?: string | null;
  description: string;
  source?: string;
}) {
  return sendJson<JobIngestResponse>("/jobs/ingest", "POST", payload);
}

export function getRuns(params: URLSearchParams) {
  return fetchJson<RunListResponse>("/runs", params);
}

export function getRunApplications(runId: string, params: URLSearchParams) {
  return fetchJson<RunApplicationsResponse>(`/runs/${runId}/applications`, params);
}

export function getResumes(params: URLSearchParams) {
  return fetchJson<ResumeListResponse>("/resumes", params);
}

export function createResume(payload: {
  user_id: number;
  name: string;
  prompt_key?: string | null;
  classification_key?: string | null;
  content: string;
  is_active: boolean;
  is_default: boolean;
}) {
  return sendJson<Resume>("/resumes", "POST", payload);
}

export function updateResume(
  resumeId: number,
  payload: {
    name?: string;
    prompt_key?: string | null;
    classification_key?: string | null;
    content?: string;
    is_active?: boolean;
    is_default?: boolean;
  },
) {
  return sendJson<Resume>(`/resumes/${resumeId}`, "PUT", payload);
}

export function getPromptLibrary(params: URLSearchParams) {
  return fetchJson<PromptLibraryListResponse>("/prompt-library", params);
}

export function createPromptLibrary(payload: {
  prompt_key: string;
  prompt_type: string;
  prompt_version: number;
  system_prompt: string;
  user_prompt_template: string;
  context?: string | null;
  max_tokens?: number | null;
  temperature?: number | null;
  is_active: boolean;
}) {
  return sendJson<PromptLibrary>("/prompt-library", "POST", payload);
}

export function updatePromptLibrary(
  promptId: number,
  payload: {
    prompt_key?: string;
    prompt_type?: string;
    prompt_version?: number;
    system_prompt?: string;
    user_prompt_template?: string;
    context?: string | null;
    max_tokens?: number | null;
    temperature?: number | null;
    is_active?: boolean;
  },
) {
  return sendJson<PromptLibrary>(`/prompt-library/${promptId}`, "PUT", payload);
}

export function deletePromptLibrary(promptId: number) {
  return sendJson<{ deleted: boolean; id: number }>(`/prompt-library/${promptId}`, "DELETE");
}
