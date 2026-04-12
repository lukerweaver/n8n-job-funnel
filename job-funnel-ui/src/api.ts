import type {
  ApplicationStatisticsResponse,
  ApplicationScoreRunRequest,
  ApplicationScoreRunResponse,
  ClassificationRunRequest,
  ClassificationRunResponse,
  InterviewRound,
  InterviewRoundListResponse,
  JobApplicationListResponse,
  JobApplication,
  AppSettings,
  OnboardingStatusResponse,
  PasteJobResponse,
  PromptLibrary,
  PromptLibraryListResponse,
  Resume,
  ResumeListResponse,
  RunApplicationsResponse,
  RunListResponse,
  StatisticsResponse,
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

export function getOnboardingStatus() {
  return fetchJson<OnboardingStatusResponse>("/onboarding/status");
}

export function completeOnboarding(payload: {
  profile_name: string;
  resume_name?: string | null;
  resume_content: string;
  target_roles: string[];
  provider: {
    provider_mode: "ollama" | "hosted" | "configure_later";
    provider_name?: string | null;
    provider_base_url?: string | null;
    provider_api_key?: string | null;
    provider_model?: string | null;
  };
}) {
  return sendJson<OnboardingStatusResponse>("/onboarding/complete", "POST", payload);
}

export function getSettings() {
  return fetchJson<AppSettings>("/settings");
}

export function updateSettings(payload: {
  profile_name?: string | null;
  target_roles?: string[] | null;
  provider?: {
    provider_mode: "ollama" | "hosted" | "configure_later";
    provider_name?: string | null;
    provider_base_url?: string | null;
    provider_api_key?: string | null;
    provider_model?: string | null;
  } | null;
  default_prompt_key?: string | null;
  scoring_preferences?: Record<string, unknown> | null;
  automation_settings?: Record<string, unknown> | null;
  advanced_mode_enabled?: boolean | null;
}) {
  return sendJson<AppSettings>("/settings", "PUT", payload);
}

export function pasteJob(payload: {
  input_type?: "url" | "description";
  url?: string | null;
  description?: string | null;
  title?: string | null;
  company_name?: string | null;
  location?: string | null;
  process_now: boolean;
  mode?: "async" | "sync";
}) {
  return sendJson<PasteJobResponse>("/jobs/paste", "POST", payload);
}

export function getApplication(applicationId: number) {
  return fetchJson<JobApplication>(`/applications/${applicationId}`);
}

export function updateApplicationStatus(
  applicationId: number,
  payload: {
    status: string;
    applied_at?: string | null;
    applied_notes?: string | null;
    screening_at?: string | null;
    screening_notes?: string | null;
    offer_at?: string | null;
    offer_notes?: string | null;
    rejected_at?: string | null;
    rejected_notes?: string | null;
    ghosted_at?: string | null;
    ghosted_notes?: string | null;
    withdrawn_at?: string | null;
    withdrawn_notes?: string | null;
    passed_at?: string | null;
    passed_notes?: string | null;
  },
) {
  return sendJson<JobApplication>(`/applications/${applicationId}/status`, "POST", payload);
}

export function updateApplicationLifecycleDates(
  applicationId: number,
  payload: {
    applied_at?: string | null;
    applied_notes?: string | null;
    screening_at?: string | null;
    screening_notes?: string | null;
    offer_at?: string | null;
    offer_notes?: string | null;
    rejected_at?: string | null;
    rejected_notes?: string | null;
    ghosted_at?: string | null;
    ghosted_notes?: string | null;
    withdrawn_at?: string | null;
    withdrawn_notes?: string | null;
    passed_at?: string | null;
    passed_notes?: string | null;
  },
) {
  return sendJson<JobApplication>(`/applications/${applicationId}/lifecycle-dates`, "PUT", payload);
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

export function getRuns(params: URLSearchParams) {
  return fetchJson<RunListResponse>("/runs", params);
}

export function createClassificationRun(payload: ClassificationRunRequest) {
  return sendJson<ClassificationRunResponse>("/jobs/classify/run", "POST", payload);
}

export function createApplicationScoreRun(payload: ApplicationScoreRunRequest) {
  return sendJson<ApplicationScoreRunResponse>("/applications/score/run", "POST", payload);
}

export async function runApplicationScore(
  applicationId: number,
  payload: {
    classification_key?: string | null;
    prompt_key?: string | null;
    force: boolean;
    refresh_resume_match?: boolean;
  },
) {
  await sendJson(`/applications/${applicationId}/score/run`, "POST", payload);
  return getApplication(applicationId);
}

export function getRunApplications(runId: string, params: URLSearchParams) {
  return fetchJson<RunApplicationsResponse>(`/runs/${runId}/applications`, params);
}

export function getStatistics(params: URLSearchParams) {
  return fetchJson<StatisticsResponse>("/statistics/job-postings", params);
}

export function getApplicationStatistics(params: URLSearchParams) {
  return fetchJson<ApplicationStatisticsResponse>("/statistics/applications", params);
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
