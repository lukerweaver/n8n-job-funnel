import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getApplications } from "../api";
import { PaginationControls } from "../components/PaginationControls";
import type { JobApplication } from "../types";
import { formatDate, moneyRange, renderListish } from "../utils";

const APPLICATION_STATUSES = ["", "scored", "new", "tailored", "notified", "applied", "screening", "interview", "offer", "rejected", "withdrawn"];
const DEFAULT_LIMIT = 25;

export function ApplicationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<JobApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobApplication | null>(null);

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("limit")) {
      next.set("limit", String(DEFAULT_LIMIT));
    }
    if (!next.get("status")) {
      next.set("status", "scored");
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
          current ? response.items.find((item) => item.id === current.id) ?? response.items[0] ?? null : response.items[0] ?? null,
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

  function updateParam(key: string, value: string) {
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
  }

  function clearFilters() {
    setSearchParams({
      limit: String(DEFAULT_LIMIT),
      status: "scored",
      sort_by: "score",
      sort_order: "desc",
      offset: "0",
    });
  }

  const limit = Number(params.get("limit") ?? String(DEFAULT_LIMIT));
  const offset = Number(params.get("offset") ?? "0");

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 1</p>
          <h2>Scored Applications</h2>
        </div>
        <div className="stat-chip">{total} matching rows</div>
      </div>

      <div className="panel filter-panel">
        <div className="filter-grid">
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

      <div className="content-grid">
        <div className="panel table-panel">
          {loading ? <p className="state-message">Loading applications...</p> : null}
          {error ? <p className="state-message error-message">{error}</p> : null}
          {!loading && !error && data.length === 0 ? <p className="state-message">No scored applications match current filters.</p> : null}

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
                  </tr>
                </thead>
                <tbody>
                  {data.map((application) => (
                    <tr
                      key={application.id}
                      className={selected?.id === application.id ? "is-selected" : ""}
                      onClick={() => setSelected(application)}
                    >
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

        <aside className="panel detail-panel">
          {selected ? (
            <>
              <div className="detail-header">
                <p className="eyebrow">Application #{selected.id}</p>
                <h3>{selected.title ?? "Untitled role"}</h3>
                <p>{selected.company_name ?? "Unknown company"}</p>
              </div>

              <div className="detail-section">
                <h4>Summary</h4>
                <dl className="detail-list">
                  <div>
                    <dt>Score</dt>
                    <dd>{selected.score ?? "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Screening</dt>
                    <dd>{selected.screening_likelihood ?? "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Recommendation</dt>
                    <dd>{selected.recommendation ?? "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Compensation</dt>
                    <dd>{moneyRange(selected.yearly_min_compensation, selected.yearly_max_compensation)}</dd>
                  </div>
                </dl>
              </div>

              <div className="detail-section">
                <h4>Rationale</h4>
                <p>{selected.justification ?? "No justification captured."}</p>
                <p><strong>Gating flags:</strong> {renderListish(selected.gating_flags)}</p>
                <p><strong>Strengths:</strong> {renderListish(selected.strengths)}</p>
                <p><strong>Gaps:</strong> {renderListish(selected.gaps)}</p>
              </div>

              <div className="detail-section">
                <h4>Metadata</h4>
                <dl className="detail-list">
                  <div>
                    <dt>Job ID</dt>
                    <dd className="mono">{selected.job_id ?? "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Classification</dt>
                    <dd>{selected.classification_key ?? "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Resume</dt>
                    <dd>{selected.resume_name ?? "N/A"}</dd>
                  </div>
                  <div>
                    <dt>Scored At</dt>
                    <dd>{formatDate(selected.scored_at)}</dd>
                  </div>
                </dl>
                {selected.apply_url ? (
                  <a className="action-link" href={selected.apply_url} target="_blank" rel="noreferrer">
                    Open Apply URL
                  </a>
                ) : null}
              </div>
            </>
          ) : (
            <p className="state-message">Select a row to inspect the scoring detail.</p>
          )}
        </aside>
      </div>
    </section>
  );
}
