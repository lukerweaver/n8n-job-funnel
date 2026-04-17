import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { createJobDescription, getApplications, runApplicationScore } from "../api";
import { ApplicationDetailModal } from "../components/ApplicationDetailModal";
import { DetailModal } from "../components/DetailModal";
import { PaginationControls } from "../components/PaginationControls";
import type { JobApplication } from "../types";
import { formatDate } from "../utils";

const APPLICATION_STATUSES = ["", "scored", "new", "tailored", "notified", "applied", "screening", "interview", "offer", "rejected", "ghosted", "withdrawn", "pass"];
const APPLICATION_RECOMMENDATIONS = ["", "Strong Apply", "Apply", "Selective Apply", "Pass"];
const DEFAULT_LIMIT = 25;

interface JobDescriptionFormState {
  company_name: string;
  title: string;
  apply_url: string;
  posted_at: string;
  description: string;
}

const EMPTY_JOB_DESCRIPTION_FORM: JobDescriptionFormState = {
  company_name: "",
  title: "",
  apply_url: "",
  posted_at: "",
  description: "",
};

function buildManualJobId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `manual-${crypto.randomUUID()}`;
  }

  return `manual-${Date.now()}`;
}

export function ApplicationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<JobApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobApplication | null>(null);
  const [searchInput, setSearchInput] = useState(searchParams.get("q") ?? "");
  const [isCreatingJobDescription, setIsCreatingJobDescription] = useState(false);
  const [jobDescriptionForm, setJobDescriptionForm] = useState<JobDescriptionFormState>(EMPTY_JOB_DESCRIPTION_FORM);
  const [jobDescriptionSubmitError, setJobDescriptionSubmitError] = useState<string | null>(null);
  const [jobDescriptionSuccess, setJobDescriptionSuccess] = useState<string | null>(null);
  const [submittingJobDescription, setSubmittingJobDescription] = useState(false);
  const [rescoringId, setRescoringId] = useState<number | null>(null);
  const [rescoreMessage, setRescoreMessage] = useState<string | null>(null);

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("limit")) {
      next.set("limit", String(DEFAULT_LIMIT));
    }
    if (!next.get("sort_by")) {
      next.set("sort_by", "score");
    }
    if (!next.get("sort_order")) {
      next.set("sort_order", "desc");
    }
    return next;
  }, [searchParams]);

  useEffect(() => {
    setSearchInput(searchParams.get("q") ?? "");
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getApplications(params)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setData(response.items);
        setTotal(response.total);
        setSelected((current) =>
          current ? response.items.find((item) => item.id === current.id) ?? null : null,
        );
      })
      .catch((requestError: Error) => {
        if (!cancelled) {
          setError(requestError.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [params]);

  const updateParam = useCallback((key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    if (key !== "offset") {
      next.set("offset", "0");
    }
    setSearchParams(next);
  }, [params, setSearchParams]);

  function clearFilters() {
    setSearchParams({
      limit: String(DEFAULT_LIMIT),
      sort_by: "score",
      sort_order: "desc",
      offset: "0",
    });
  }

  const limit = Number(params.get("limit") ?? String(DEFAULT_LIMIT));
  const offset = Number(params.get("offset") ?? "0");
  const selectedIndex = selected ? data.findIndex((item) => item.id === selected.id) : -1;

  useEffect(() => {
    const currentQuery = params.get("q") ?? "";
    if (searchInput === currentQuery) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      updateParam("q", searchInput);
    }, 1000);

    return () => window.clearTimeout(timeoutId);
  }, [params, searchInput, updateParam]);

  useEffect(() => {
    if (!selected) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelected(null);
      }
      if (event.key === "ArrowLeft" && selectedIndex > 0) {
        setSelected(data[selectedIndex - 1]);
      }
      if (event.key === "ArrowRight" && selectedIndex >= 0 && selectedIndex < data.length - 1) {
        setSelected(data[selectedIndex + 1]);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [data, selected, selectedIndex]);

  useEffect(() => {
    if (!isCreatingJobDescription) {
      setJobDescriptionForm(EMPTY_JOB_DESCRIPTION_FORM);
      setJobDescriptionSubmitError(null);
    }
  }, [isCreatingJobDescription]);

  function openCreateJobDescriptionModal() {
    setJobDescriptionSuccess(null);
    setJobDescriptionSubmitError(null);
    setJobDescriptionForm(EMPTY_JOB_DESCRIPTION_FORM);
    setIsCreatingJobDescription(true);
  }

  async function handleCreateJobDescription(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittingJobDescription(true);
    setJobDescriptionSubmitError(null);
    setJobDescriptionSuccess(null);

    const payload = {
      job_id: buildManualJobId(),
      company_name: jobDescriptionForm.company_name.trim() || null,
      title: jobDescriptionForm.title.trim() || null,
      apply_url: jobDescriptionForm.apply_url.trim() || null,
      posted_at: jobDescriptionForm.posted_at ? `${jobDescriptionForm.posted_at}T00:00:00Z` : null,
      posted_at_raw: jobDescriptionForm.posted_at || null,
      description: jobDescriptionForm.description.trim(),
      source: "manual-entry",
    };

    try {
      const response = await createJobDescription(payload);
      setIsCreatingJobDescription(false);
      setJobDescriptionForm(EMPTY_JOB_DESCRIPTION_FORM);
      setJobDescriptionSuccess(`Created job description ${response.jobs[0] ?? payload.job_id}.`);
    } catch (requestError) {
      setJobDescriptionSubmitError(
        requestError instanceof Error ? requestError.message : "Unable to create job description.",
      );
    } finally {
      setSubmittingJobDescription(false);
    }
  }

  async function handleRescore(application: JobApplication) {
    setRescoringId(application.id);
    setError(null);
    setRescoreMessage(null);

    try {
      const updated = await runApplicationScore(application.id, {
        force: true,
        refresh_resume_match: true,
      });
      setData((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelected((current) => (current?.id === updated.id ? updated : current));
      setRescoreMessage(`Rescored application #${updated.id} using ${updated.resume_name ?? "the matched resume"}.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to re-score application.");
    } finally {
      setRescoringId(null);
    }
  }

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 1</p>
          <h2>Scored Applications</h2>
        </div>
        <div className="page-actions">
          <div className="stat-chip">{total} matching rows</div>
          <button type="button" className="primary-button" onClick={openCreateJobDescriptionModal}>
            Add Job Description
          </button>
        </div>
      </div>

      {jobDescriptionSuccess ? <p className="success-callout">{jobDescriptionSuccess}</p> : null}
      {rescoreMessage ? <p className="success-callout">{rescoreMessage}</p> : null}

      <div className="panel filter-panel">
        <div className="filter-grid">
          <label>
            Search
            <input
              type="text"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Company, title, or job id"
            />
          </label>

          <label>
            Status
            <select value={params.get("status") ?? ""} onChange={(event) => updateParam("status", event.target.value)}>
              {APPLICATION_STATUSES.map((status) => (
                <option key={status || "all"} value={status}>
                  {status || "All"}
                </option>
              ))}
            </select>
          </label>

          <label>
            Recommendation
            <select
              value={params.get("recommendation") ?? ""}
              onChange={(event) => updateParam("recommendation", event.target.value)}
            >
              {APPLICATION_RECOMMENDATIONS.map((recommendation) => (
                <option key={recommendation || "all"} value={recommendation}>
                  {recommendation || "All"}
                </option>
              ))}
            </select>
          </label>

          <label>
            Score Min
            <input
              type="number"
              value={params.get("score_min") ?? ""}
              onChange={(event) => updateParam("score_min", event.target.value)}
              placeholder="20"
            />
          </label>

          <label>
            Score Max
            <input
              type="number"
              value={params.get("score_max") ?? ""}
              onChange={(event) => updateParam("score_max", event.target.value)}
              placeholder="90"
            />
          </label>

          <label>
            User ID
            <input
              type="number"
              value={params.get("user_id") ?? ""}
              onChange={(event) => updateParam("user_id", event.target.value)}
              placeholder="1"
            />
          </label>

          <label>
            Resume ID
            <input
              type="number"
              value={params.get("resume_id") ?? ""}
              onChange={(event) => updateParam("resume_id", event.target.value)}
              placeholder="4"
            />
          </label>

          <label>
            Classification
            <input
              type="text"
              value={params.get("classification_key") ?? ""}
              onChange={(event) => updateParam("classification_key", event.target.value)}
              placeholder="Product Manager"
            />
          </label>

          <label>
            Updated Since
            <input
              type="datetime-local"
              value={params.get("updated_since") ?? ""}
              onChange={(event) => updateParam("updated_since", event.target.value)}
            />
          </label>

          <label>
            Page Size
            <select value={String(limit)} onChange={(event) => updateParam("limit", event.target.value)}>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </label>

          <label>
            Sort By
            <select value={params.get("sort_by") ?? "score"} onChange={(event) => updateParam("sort_by", event.target.value)}>
              <option value="score">Score</option>
              <option value="scored_at">Scored At</option>
              <option value="posted_at">Posted Date</option>
              <option value="created_at">Created At</option>
              <option value="updated_at">Updated At</option>
              <option value="status">Status</option>
            </select>
          </label>

          <label>
            Sort Order
            <select value={params.get("sort_order") ?? "desc"} onChange={(event) => updateParam("sort_order", event.target.value)}>
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </select>
          </label>

          <div className="filter-actions">
            <button type="button" className="secondary-button" onClick={clearFilters}>
              Reset
            </button>
          </div>
        </div>
      </div>

      <div className="panel table-panel">
        {loading ? <p className="state-message">Loading applications...</p> : null}
        {error ? <p className="state-message error-message">{error}</p> : null}
        {!loading && !error && data.length === 0 ? <p className="state-message">No applications match current filters.</p> : null}

        {!loading && !error && data.length > 0 ? (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Title</th>
                  <th>Score</th>
                  <th>Screening</th>
                  <th>Recommendation</th>
                  <th>Classification</th>
                  <th>Resume</th>
                  <th>Status</th>
                  <th>Posted At</th>
                  <th>Scored</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.map((application) => (
                  <tr key={application.id} onClick={() => setSelected(application)}>
                    <td>{application.company_name ?? "Unknown"}</td>
                    <td>{application.title ?? "Untitled role"}</td>
                    <td>{application.score ?? "N/A"}</td>
                    <td>{application.screening_likelihood ?? "N/A"}</td>
                    <td>{application.recommendation ?? "N/A"}</td>
                    <td>{application.classification_key ?? "N/A"}</td>
                    <td>{application.resume_name ?? "N/A"}</td>
                    <td>
                      <span className={`status-pill status-${application.status}`}>{application.status}</span>
                    </td>
                    <td>{application.posted_at ? formatDate(application.posted_at) : application.posted_at_raw ?? "N/A"}</td>
                    <td>{formatDate(application.scored_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="action-button table-action-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleRescore(application);
                        }}
                        disabled={rescoringId !== null}
                      >
                        {rescoringId === application.id ? "Rescoring..." : "Rescore"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <PaginationControls
              total={total}
              limit={limit}
              offset={offset}
              onPageChange={(nextOffset) => updateParam("offset", String(nextOffset))}
            />
          </>
        ) : null}
      </div>

      {selected ? (
        <ApplicationDetailModal
          applicationId={selected.id}
          fallbackTitle={selected.title ?? "Untitled role"}
          fallbackSubtitle={`Application #${selected.id} · ${selected.company_name ?? "Unknown company"}`}
          onClose={() => setSelected(null)}
          onPrevious={() => setSelected(data[selectedIndex - 1])}
          onNext={() => setSelected(data[selectedIndex + 1])}
          previousDisabled={selectedIndex <= 0}
          nextDisabled={selectedIndex === -1 || selectedIndex >= data.length - 1}
          onApplicationUpdated={(updated) => {
            setData((current) => current.map((item) => (item.id === updated.id ? updated : item)));
            setSelected(updated);
          }}
        />
      ) : null}

      {isCreatingJobDescription ? (
        <DetailModal
          title="New Job Description"
          subtitle="Create a manual job posting from the applications page"
          onClose={() => setIsCreatingJobDescription(false)}
        >
          <form className="editor-form" onSubmit={handleCreateJobDescription}>
            <div className="inline-form-grid">
              <label>
                Company Name
                <input
                  type="text"
                  value={jobDescriptionForm.company_name}
                  onChange={(event) =>
                    setJobDescriptionForm((current) => ({ ...current, company_name: event.target.value }))
                  }
                  placeholder="Acme Corp"
                />
              </label>

              <label>
                Job Title
                <input
                  type="text"
                  value={jobDescriptionForm.title}
                  onChange={(event) => setJobDescriptionForm((current) => ({ ...current, title: event.target.value }))}
                  placeholder="Senior Product Manager"
                />
              </label>
            </div>

            <label>
              Apply URL
              <input
                type="url"
                value={jobDescriptionForm.apply_url}
                onChange={(event) => setJobDescriptionForm((current) => ({ ...current, apply_url: event.target.value }))}
                placeholder="https://example.com/jobs/123"
              />
            </label>

            <label>
              Posted Date
              <input
                type="date"
                value={jobDescriptionForm.posted_at}
                onChange={(event) =>
                  setJobDescriptionForm((current) => ({ ...current, posted_at: event.target.value }))
                }
              />
            </label>

            <label>
              Job Description
              <textarea
                className="editor-textarea"
                value={jobDescriptionForm.description}
                onChange={(event) =>
                  setJobDescriptionForm((current) => ({ ...current, description: event.target.value }))
                }
                required
              />
            </label>

            {jobDescriptionSubmitError ? <p className="error-callout">{jobDescriptionSubmitError}</p> : null}

            <div className="form-actions">
              <button type="submit" className="primary-button" disabled={submittingJobDescription}>
                {submittingJobDescription ? "Creating..." : "Create Job Description"}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setIsCreatingJobDescription(false)}
                disabled={submittingJobDescription}
              >
                Cancel
              </button>
            </div>
          </form>
        </DetailModal>
      ) : null}
    </section>
  );
}
