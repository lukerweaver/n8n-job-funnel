import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getRunApplications } from "../api";
import { DetailModal } from "../components/DetailModal";
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
      next.set("sort_by", "score");
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
    next.set("offset", "0");
    setSearchParams(next);
  }

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
  const selectedIndex = selected ? data.findIndex((item) => item.run_item_id === selected.run_item_id) : -1;

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
        <div className="stat-chip">{total} application-linked rows</div>
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
            <select value={params.get("sort_by") ?? "score"} onChange={(event) => updateParam("sort_by", event.target.value)}>
              <option value="score">Score</option>
              <option value="screening_likelihood">Screening Likelihood</option>
              <option value="company_name">Company</option>
              <option value="title">Title</option>
              <option value="classification_key">Classification</option>
              <option value="scored_at">Scored At</option>
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
          <p className="state-message">This run has no scored applications to display for the current filters.</p>
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
                  <th>Compensation</th>
                </tr>
              </thead>
              <tbody>
                {data.map((item) => (
                  <tr key={item.run_item_id} onClick={() => setSelected(item)}>
                    <td>{item.company_name ?? "Unknown"}</td>
                    <td>{item.title ?? "Untitled role"}</td>
                    <td>{item.score ?? "N/A"}</td>
                    <td>{item.screening_likelihood ?? "N/A"}</td>
                    <td>{item.classification_key ?? "N/A"}</td>
                    <td>{item.resume_name ?? "N/A"}</td>
                    <td>
                      <span className={`status-pill status-${item.run_item_status}`}>{item.run_item_status}</span>
                    </td>
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

      {selected ? (
        <DetailModal
          title={selected.title ?? "Untitled role"}
          subtitle={`Run item #${selected.run_item_id} · ${selected.company_name ?? "Unknown company"}`}
          onClose={() => setSelected(null)}
          onPrevious={() => setSelected(data[selectedIndex - 1])}
          onNext={() => setSelected(data[selectedIndex + 1])}
          previousDisabled={selectedIndex <= 0}
          nextDisabled={selectedIndex === -1 || selectedIndex >= data.length - 1}
        >
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
                <dt>Status</dt>
                <dd>{selected.run_item_status}</dd>
              </div>
            </dl>
          </div>

          <div className="detail-section">
            <h4>Job</h4>
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
            {selected.run_item_error_message ? (
              <p className="error-callout">{selected.run_item_error_message}</p>
            ) : null}
            {selected.apply_url ? (
              <a className="action-link" href={selected.apply_url} target="_blank" rel="noreferrer">
                Open Apply URL
              </a>
            ) : null}
          </div>
        </DetailModal>
      ) : null}
    </section>
  );
}
