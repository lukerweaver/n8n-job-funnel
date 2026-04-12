import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getApplications, runApplicationScore } from "../api";
import { ApplicationDetailModal } from "../components/ApplicationDetailModal";
import { PaginationControls } from "../components/PaginationControls";
import type { JobApplication } from "../types";
import { formatDate } from "../utils";

const APPLICATION_STATUSES = ["", "scored", "new", "tailored", "notified", "applied", "screening", "interview", "offer", "rejected", "ghosted", "withdrawn", "pass"];
const APPLICATION_RECOMMENDATIONS = ["", "Strong Apply", "Apply", "Selective Apply", "Pass"];
const DEFAULT_LIMIT = 25;

export function ApplicationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<JobApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobApplication | null>(null);
  const [searchInput, setSearchInput] = useState(searchParams.get("q") ?? "");
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
        </div>
      </div>

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

    </section>
  );
}
