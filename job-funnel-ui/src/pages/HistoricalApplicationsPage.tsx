import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getApplications } from "../api";
import { ApplicationDetailModal } from "../components/ApplicationDetailModal";
import { PaginationControls } from "../components/PaginationControls";
import type { JobApplication } from "../types";
import { formatDate } from "../utils";

const DEFAULT_LIMIT = 25;
const HISTORICAL_APPLICATION_STATUSES = ["applied", "screening", "interview", "offer", "rejected", "ghosted", "withdrawn", "pass"];

export function HistoricalApplicationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<JobApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobApplication | null>(null);
  const [searchInput, setSearchInput] = useState(searchParams.get("q") ?? "");

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("limit")) {
      next.set("limit", String(DEFAULT_LIMIT));
    }
    if (!next.get("status_group")) {
      next.set("status_group", "historical");
    }
    if (!next.get("sort_by")) {
      next.set("sort_by", "updated_at");
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
        setSelected((current) => (current ? response.items.find((item) => item.id === current.id) ?? null : null));
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
      status_group: "historical",
      sort_by: "updated_at",
      sort_order: "desc",
      offset: "0",
    });
  }

  const limit = Number(params.get("limit") ?? String(DEFAULT_LIMIT));
  const offset = Number(params.get("offset") ?? "0");
  const selectedIndex = selected ? data.findIndex((item) => item.id === selected.id) : -1;
  const terminalCount = data.filter((item) => ["offer", "rejected", "ghosted", "withdrawn", "pass"].includes(item.status)).length;

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

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 3</p>
          <h2>Historical Applications</h2>
          <p className="page-subtitle">Applied applications across active and completed lifecycle states.</p>
        </div>
        <div className="page-actions">
          <div className="stat-chip">{total} historical applications</div>
          <div className="stat-chip">{terminalCount} completed outcomes</div>
        </div>
      </div>

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
              <option value="">All</option>
              {HISTORICAL_APPLICATION_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
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
        {loading ? <p className="state-message">Loading historical applications...</p> : null}
        {error ? <p className="state-message error-message">{error}</p> : null}
        {!loading && !error && data.length === 0 ? <p className="state-message">No historical applications match current filters.</p> : null}

        {!loading && !error && data.length > 0 ? (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Applied</th>
                  <th>Next Interview</th>
                  <th>Rounds</th>
                  <th>Resume</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {data.map((application) => (
                  <tr key={application.id} onClick={() => setSelected(application)}>
                    <td>{application.company_name ?? "Unknown"}</td>
                    <td>{application.title ?? "Untitled role"}</td>
                    <td>
                      <span className={`status-pill status-${application.status}`}>{application.status}</span>
                    </td>
                    <td>{formatDate(application.applied_at)}</td>
                    <td>{formatDate(application.next_interview_at)}</td>
                    <td>{application.interview_rounds_total}</td>
                    <td>{application.resume_name ?? "N/A"}</td>
                    <td>{formatDate(application.updated_at)}</td>
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
            setData((current) => {
              const next = current
                .map((item) => (item.id === updated.id ? updated : item))
                .filter((item) => HISTORICAL_APPLICATION_STATUSES.includes(item.status));
              return next;
            });
            if (HISTORICAL_APPLICATION_STATUSES.includes(updated.status)) {
              setSelected(updated);
            } else {
              setSelected(null);
            }
          }}
        />
      ) : null}
    </section>
  );
}
