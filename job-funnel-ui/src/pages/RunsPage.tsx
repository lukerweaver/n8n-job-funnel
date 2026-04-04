import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getRuns } from "../api";
import { PaginationControls } from "../components/PaginationControls";
import type { Run } from "../types";
import { formatDate } from "../utils";

const DEFAULT_LIMIT = 25;

export function RunsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("limit")) {
      next.set("limit", String(DEFAULT_LIMIT));
    }
    return next;
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getRuns(params)
      .then((response) => {
        if (!cancelled) {
          setData(response.items);
          setTotal(response.total);
        }
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
      offset: "0",
    });
  }

  const limit = Number(params.get("limit") ?? String(DEFAULT_LIMIT));
  const offset = Number(params.get("offset") ?? "0");

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 2</p>
          <h2>Runs</h2>
        </div>
        <div className="stat-chip">{total} visible runs</div>
      </div>

      <div className="panel filter-panel">
        <div className="filter-grid">
          <label>
            Type
            <select value={params.get("type") ?? ""} onChange={(event) => updateParam("type", event.target.value)}>
              <option value="">All</option>
              <option value="classification">Classification</option>
              <option value="application_scoring">Application Scoring</option>
            </select>
          </label>

          <label>
            Status
            <select value={params.get("status") ?? ""} onChange={(event) => updateParam("status", event.target.value)}>
              <option value="">All</option>
              <option value="queued">queued</option>
              <option value="running">running</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
            </select>
          </label>

          <label>
            Requested Status
            <input
              type="text"
              value={params.get("requested_status") ?? ""}
              onChange={(event) => updateParam("requested_status", event.target.value)}
              placeholder="new"
            />
          </label>

          <label>
            Requested Source
            <input
              type="text"
              value={params.get("requested_source") ?? ""}
              onChange={(event) => updateParam("requested_source", event.target.value)}
              placeholder="linkedin"
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
            Prompt Key
            <input
              type="text"
              value={params.get("prompt_key") ?? ""}
              onChange={(event) => updateParam("prompt_key", event.target.value)}
              placeholder="classifier-v1"
            />
          </label>

          <label>
            Callback Status
            <select value={params.get("callback_status") ?? ""} onChange={(event) => updateParam("callback_status", event.target.value)}>
              <option value="">All</option>
              <option value="delivered">delivered</option>
              <option value="failed">failed</option>
            </select>
          </label>

          <label>
            Created Since
            <input
              type="datetime-local"
              value={params.get("created_since") ?? ""}
              onChange={(event) => updateParam("created_since", event.target.value)}
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

          <div className="filter-actions">
            <button type="button" className="secondary-button" onClick={clearFilters}>
              Reset
            </button>
          </div>
        </div>
      </div>

      <div className="panel table-panel">
        {loading ? <p className="state-message">Loading runs...</p> : null}
        {error ? <p className="state-message error-message">{error}</p> : null}
        {!loading && !error && data.length === 0 ? <p className="state-message">No runs match current filters.</p> : null}

        {!loading && !error && data.length > 0 ? (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Selected</th>
                  <th>Processed</th>
                  <th>Succeeded</th>
                  <th>Errored</th>
                  <th>Skipped</th>
                  <th>Prompt</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {data.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <Link className="table-link mono" to={`/runs/${run.run_id}`}>
                        #{run.run_id}
                      </Link>
                    </td>
                    <td>{run.type}</td>
                    <td>
                      <span className={`status-pill status-${run.status}`}>{run.status}</span>
                    </td>
                    <td>{run.selected}</td>
                    <td>{run.processed}</td>
                    <td>{run.succeeded}</td>
                    <td>{run.errored}</td>
                    <td>{run.skipped}</td>
                    <td>{run.prompt_key ?? "N/A"}</td>
                    <td>{formatDate(run.created_at)}</td>
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
    </section>
  );
}
