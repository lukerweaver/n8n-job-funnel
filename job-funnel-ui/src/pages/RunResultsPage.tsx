import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getRunApplications } from "../api";
import { ApplicationDetailModal } from "../components/ApplicationDetailModal";
import { PaginationControls } from "../components/PaginationControls";
import type { RunApplication } from "../types";
import { formatDate, moneyRange } from "../utils";

const DEFAULT_LIMIT = 25;

export function RunResultsPage() {
  const { runId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<RunApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<RunApplication | null>(null);

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("limit")) {
      next.set("limit", String(DEFAULT_LIMIT));
    }
    if (!next.get("sort_by")) {
      next.set("sort_by", "created_at");
    }
    if (!next.get("sort_order")) {
      next.set("sort_order", "desc");
    }
    return next;
  }, [searchParams]);

  useEffect(() => {
    if (!runId) {
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getRunApplications(runId, params)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setData(response.items);
        setTotal(response.total);
        setSelected((current) =>
          current ? response.items.find((item) => item.run_item_id === current.run_item_id) ?? null : null,
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
  }, [params, runId]);

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
      sort_by: "created_at",
      sort_order: "desc",
      offset: "0",
    });
  }

  const limit = Number(params.get("limit") ?? String(DEFAULT_LIMIT));
  const offset = Number(params.get("offset") ?? "0");
  const selectedIndex = selected ? data.findIndex((item) => item.run_item_id === selected.run_item_id) : -1;
  const previousApplication =
    selectedIndex > 0 ? data.slice(0, selectedIndex).reverse().find((item) => item.job_application_id !== null) ?? null : null;
  const nextApplication =
    selectedIndex >= 0 ? data.slice(selectedIndex + 1).find((item) => item.job_application_id !== null) ?? null : null;

  useEffect(() => {
    if (!selected) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelected(null);
      }
      if (event.key === "ArrowLeft" && previousApplication) {
        setSelected(previousApplication);
      }
      if (event.key === "ArrowRight" && nextApplication) {
        setSelected(nextApplication);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [nextApplication, previousApplication, selected]);

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 3</p>
          <h2>Run Results</h2>
          <p className="page-subtitle">
            <Link className="inline-back-link" to="/runs">
              Back to runs
            </Link>
            {runId ? `Run #${runId}` : ""}
          </p>
        </div>
        <div className="stat-chip">{total} run items</div>
      </div>

      <div className="panel filter-panel">
        <div className="filter-grid">
          <label>
            Run Item Status
            <select
              value={params.get("run_item_status") ?? ""}
              onChange={(event) => updateParam("run_item_status", event.target.value)}
            >
              <option value="">All</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="scored">scored</option>
              <option value="classified">classified</option>
              <option value="skipped">skipped</option>
              <option value="error">error</option>
            </select>
          </label>

          <label>
            Score Min
            <input
              type="number"
              value={params.get("score_min") ?? ""}
              onChange={(event) => updateParam("score_min", event.target.value)}
              placeholder="30"
            />
          </label>

          <label>
            Score Max
            <input
              type="number"
              value={params.get("score_max") ?? ""}
              onChange={(event) => updateParam("score_max", event.target.value)}
              placeholder="95"
            />
          </label>

          <label>
            Sort By
            <select value={params.get("sort_by") ?? "created_at"} onChange={(event) => updateParam("sort_by", event.target.value)}>
              <option value="score">Score</option>
              <option value="screening_likelihood">Screening Likelihood</option>
              <option value="company_name">Company</option>
              <option value="title">Title</option>
              <option value="classification_key">Classification</option>
              <option value="classified_at">Classified At</option>
              <option value="scored_at">Scored At</option>
              <option value="created_at">Run Item Created</option>
            </select>
          </label>

          <label>
            Sort Order
            <select value={params.get("sort_order") ?? "desc"} onChange={(event) => updateParam("sort_order", event.target.value)}>
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </select>
          </label>

          <label>
            Page Size
            <select value={String(limit)} onChange={(event) => updateParam("limit", event.target.value)}>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
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
        {loading ? <p className="state-message">Loading run results...</p> : null}
        {error ? <p className="state-message error-message">{error}</p> : null}
        {!loading && !error && data.length === 0 ? (
          <p className="state-message">This run has no items to display for the current filters.</p>
        ) : null}

        {!loading && !error && data.length > 0 ? (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Title</th>
                  <th>Score</th>
                  <th>Screening</th>
                  <th>Classification</th>
                  <th>Resume</th>
                  <th>Run Item</th>
                  <th>Issue</th>
                  <th>Posted At</th>
                  <th>Compensation</th>
                </tr>
              </thead>
              <tbody>
                {data.map((item) => (
                  <tr
                    key={item.run_item_id}
                    className={item.job_application_id === null ? "noninteractive-row" : undefined}
                    onClick={() => {
                      if (item.job_application_id !== null) {
                        setSelected(item);
                      }
                    }}
                  >
                    <td>{item.company_name ?? "Unknown"}</td>
                    <td>{item.title ?? "Untitled role"}</td>
                    <td>{item.score ?? "N/A"}</td>
                    <td>{item.screening_likelihood ?? "N/A"}</td>
                    <td>{item.classification_key ?? "N/A"}</td>
                    <td>{item.resume_name ?? "N/A"}</td>
                    <td>
                      <span className={`status-pill status-${item.run_item_status}`}>{item.run_item_status}</span>
                    </td>
                    <td>{item.run_item_error_message ?? item.classification_error ?? "N/A"}</td>
                    <td>{item.posted_at ? formatDate(item.posted_at) : item.posted_at_raw ?? "N/A"}</td>
                    <td>{moneyRange(item.yearly_min_compensation, item.yearly_max_compensation)}</td>
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

      {selected && selected.job_application_id !== null ? (
        <ApplicationDetailModal
          applicationId={selected.job_application_id}
          fallbackTitle={selected.title ?? "Untitled role"}
          fallbackSubtitle={`Run item #${selected.run_item_id} · ${selected.company_name ?? "Unknown company"}`}
          onClose={() => setSelected(null)}
          onPrevious={() => {
            if (previousApplication) {
              setSelected(previousApplication);
            }
          }}
          onNext={() => {
            if (nextApplication) {
              setSelected(nextApplication);
            }
          }}
          previousDisabled={!previousApplication}
          nextDisabled={!nextApplication}
        />
      ) : null}
    </section>
  );
}
