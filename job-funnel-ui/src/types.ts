export type ApplicationStatus =
  | "new"
  | "scored"
  | "tailored"
  | "notified"
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "rejected"
  | "ghosted"
  | "withdrawn"
  | "pass";

export type InterviewRoundStatus = "scheduled" | "completed";

export interface InterviewRound {
  id: number;
  job_application_id: number;
  round_number: number;
  stage_name: string | null;
  status: InterviewRoundStatus;
  notes: string | null;
  scheduled_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobApplication {
  id: number;
  user_id: number;
  job_posting_id: number;
  resume_id: number;
  job_id: string | null;
  source: string | null;
  company_name: string | null;
  title: string | null;
  yearly_min_compensation: number | null;
  yearly_max_compensation: number | null;
  apply_url: string | null;
  description: string | null;
  classification_key: string | null;
  resume_name: string | null;
  status: ApplicationStatus;
  score: number | null;
  recommendation: string | null;
  justification: string | null;
  screening_likelihood: number | null;
  dimension_scores: Record<string, number> | null;
  gating_flags: string[] | null;
  strengths: Array<unknown> | Record<string, unknown> | null;
  gaps: Array<unknown> | Record<string, unknown> | null;
  missing_from_jd: Array<unknown> | Record<string, unknown> | null;
  scoring_prompt_key: string | null;
  scoring_prompt_version: number | null;
  score_error: string | null;
  scored_at: string | null;
  tailored_resume_content: string | null;
  tailoring_prompt_key: string | null;
  tailoring_prompt_version: number | null;
  tailoring_error: string | null;
  tailored_at: string | null;
  notified_at: string | null;
  applied_at: string | null;
  applied_notes: string | null;
  screening_at: string | null;
  screening_notes: string | null;
  offer_at: string | null;
  offer_notes: string | null;
  rejected_at: string | null;
  rejected_notes: string | null;
  ghosted_at: string | null;
  ghosted_notes: string | null;
  withdrawn_at: string | null;
  withdrawn_notes: string | null;
  passed_at: string | null;
  passed_notes: string | null;
  last_error_at: string | null;
  next_interview_at: string | null;
  next_interview_stage: string | null;
  interview_rounds_total: number;
  created_at: string;
  updated_at: string;
}

export interface JobApplicationListResponse {
  total: number;
  items: JobApplication[];
}

export interface JobIngestResponse {
  received: number;
  created: number;
  updated: number;
  skipped: number;
  jobs: string[];
}

export interface Run {
  run_id: number;
  type: string;
  status: string;
  selected: number;
  processed: number;
  succeeded: number;
  errored: number;
  skipped: number;
  jobs: number[];
  applications: number[];
  callback_url: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  requested_status: string;
  requested_source: string | null;
  classification_key: string | null;
  prompt_key: string | null;
  force: boolean;
  callback_status: string | null;
  callback_error: string | null;
}

export interface RunListResponse {
  total: number;
  items: Run[];
}

export interface RunApplication {
  run_item_id: number;
  run_item_status: string;
  run_item_error_message: string | null;
  job_application_id: number;
  job_posting_id: number;
  resume_id: number;
  job_id: string | null;
  company_name: string | null;
  title: string | null;
  score: number | null;
  screening_likelihood: number | null;
  classification_key: string | null;
  apply_url: string | null;
  yearly_min_compensation: number | null;
  yearly_max_compensation: number | null;
  recommendation: string | null;
  resume_name: string | null;
  scored_at: string | null;
}

export interface RunApplicationsResponse {
  total: number;
  items: RunApplication[];
}

export interface ClassificationRunRequest {
  limit: number;
  source?: string | null;
  classification_key?: string | null;
  prompt_key?: string | null;
  force: boolean;
  callback_url?: string | null;
}

export interface ClassificationRunResponse {
  run_id: number;
  type: string;
  status: string;
  selected: number;
  processed: number;
  classified: number;
  errored: number;
  skipped: number;
  jobs: number[];
  applications: number[];
  callback_url: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
}

export interface ApplicationScoreRunRequest {
  limit: number;
  status: string;
  user_id?: number | null;
  resume_id?: number | null;
  job_posting_id?: number | null;
  classification_key?: string | null;
  prompt_key?: string | null;
  force: boolean;
  refresh_resume_match?: boolean;
  callback_url?: string | null;
}

export interface ApplicationScoreRunResponse {
  run_id: number;
  type: string;
  status: string;
  processed: number;
  selected: number;
  scored: number;
  errored: number;
  skipped: number;
  jobs: number[];
  applications: number[];
  callback_url: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
}

export interface DailyIngestStatistics {
  created_date: string;
  ingested_job_postings: number;
  rolling_7_day_avg_ingested: number;
  high_job_postings: number;
  rolling_7_day_avg_high: number;
  percentage_high: number | null;
  rolling_7_day_percentage: number | null;
}

export interface IngestStatisticsResponse {
  total_days: number;
  total_ingested_job_postings: number;
  total_high_job_postings: number;
  average_daily_ingested: number;
  average_daily_high: number;
  items: DailyIngestStatistics[];
}

export interface ScoreDistributionBucket {
  bucket_start: number;
  bucket_end: number;
  count: number;
}

export interface ScoreDistributionResponse {
  total_scored_jobs: number;
  average_score: number | null;
  minimum_score: number | null;
  maximum_score: number | null;
  bucket_size: number;
  buckets: ScoreDistributionBucket[];
}

export interface StatisticsResponse {
  ingested_jobs: IngestStatisticsResponse;
  score_distribution: ScoreDistributionResponse;
}

export interface InterviewRoundListResponse {
  total: number;
  items: InterviewRound[];
}

export interface Resume {
  id: number;
  user_id: number;
  name: string;
  prompt_key: string;
  classification_key: string | null;
  content: string;
  is_active: boolean;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResumeListResponse {
  total: number;
  items: Resume[];
}

export interface PromptLibrary {
  id: number;
  prompt_key: string;
  prompt_type: string;
  prompt_version: number;
  system_prompt: string;
  user_prompt_template: string;
  context: string | null;
  max_tokens: number | null;
  temperature: number | null;
  is_active: boolean;
}

export interface PromptLibraryListResponse {
  total: number;
  items: PromptLibrary[];
}
