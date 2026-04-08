import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { createApplicationScoreRun, createClassificationRun, getRuns } from "../api";
import { DetailModal } from "../components/DetailModal";
import { PaginationControls } from "../components/PaginationControls";
import type { Run } from "../types";
import { formatDate } from "../utils";

const DEFAULT_LIMIT = 25;

const DEFAULT_CLASSIFICATION_FORM = {
  limit: "25",
  source: "",
  classification_key: "",
  prompt_key: "",
  callback_url: "",
  force: false,
};

const DEFAULT_SCORING_FORM = {
  limit: "25",
  status: "new",
  user_id: "",
  resume_id: "",
  job_posting_id: "",
  classification_key: "",
  prompt_key: "",
  callback_url: "",
  force: false,
};

export function RunsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [showClassificationModal, setShowClassificationModal] = useState(false);
  const [showScoringModal, setShowScoringModal] = useState(false);
  const [classificationForm, setClassificationForm] = useState(DEFAULT_CLASSIFICATION_FORM);
  const [scoringForm, setScoringForm] = useState(DEFAULT_SCORING_FORM);
  const [classificationSubmitting, setClassificationSubmitting] = useState(false);
  const [scoringSubmitting, setScoringSubmitting] = useState(false);
  const [classificationSubmitError, setClassificationSubmitError] = useState<string | null>(null);
  const [scoringSubmitError, setScoringSubmitError] = useState<string | null>(null);
  const [runLaunchMessage, setRunLaunchMessage] = useState<string | null>(null);

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("limit")) {
      next.set("limit", String(DEFAULT_LIMIT));
    }
    return next;
  }, [searchParams]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setRefreshTick((current) => current + 1);
    }, 60000);

    return () => window.clearInterval(intervalId);
  }, []);

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
  }, [params, refreshTick]);

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

  function openClassificationModal() {
    setClassificationForm(DEFAULT_CLASSIFICATION_FORM);
    setClassificationSubmitError(null);
    setShowClassificationModal(true);
  }

  function openScoringModal() {
    setScoringForm(DEFAULT_SCORING_FORM);
    setScoringSubmitError(null);
    setShowScoringModal(true);
  }

  async function handleClassificationSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setClassificationSubmitting(true);
    setClassificationSubmitError(null);

    try {
      const result = await createClassificationRun({
        limit: Number(classificationForm.limit || "25"),
        source: classificationForm.source || null,
        classification_key: classificationForm.classification_key || null,
        prompt_key: classificationForm.prompt_key || null,
        callback_url: classificationForm.callback_url || null,
        force: classificationForm.force,
      });
      setShowClassificationModal(false);
      setRefreshTick((current) => current + 1);
      setRunLaunchMessage(`Queued classification run #${result.run_id} for ${result.selected} jobs.`);
    } catch (requestError) {
      setClassificationSubmitError(requestError instanceof Error ? requestError.message : "Failed to queue classification run.");
    } finally {
      setClassificationSubmitting(false);
    }
  }

  async function handleScoringSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setScoringSubmitting(true);
    setScoringSubmitError(null);

    try {
      const result = await createApplicationScoreRun({
        limit: Number(scoringForm.limit || "25"),
        status: scoringForm.status || "new",
        user_id: scoringForm.user_id ? Number(scoringForm.user_id) : null,
        resume_id: scoringForm.resume_id ? Number(scoringForm.resume_id) : null,
        job_posting_id: scoringForm.job_posting_id ? Number(scoringForm.job_posting_id) : null,
        classification_key: scoringForm.classification_key || null,
        prompt_key: scoringForm.prompt_key || null,
        callback_url: scoringForm.callback_url || null,
        force: scoringForm.force,
      });
      setShowScoringModal(false);
      setRefreshTick((current) => current + 1);
      setRunLaunchMessage(`Queued scoring run #${result.run_id} for ${result.selected} applications.`);
    } catch (requestError) {
      setScoringSubmitError(requestError instanceof Error ? requestError.message : "Failed to queue scoring run.");
    } finally {
      setScoringSubmitting(false);
    }
  }

  const limit = Number(params.get("limit") ?? String(DEFAULT_LIMIT));
  const offset = Number(params.get("offset") ?? "0");

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 4</p>
          <h2>Runs</h2>
          <p className="page-subtitle">Refreshes from the API every 60 seconds.</p>
        </div>
        <div className="page-actions">
          <div className="stat-chip">{total} visible runs</div>
          <button type="button" className="secondary-button" onClick={openClassificationModal}>
            New Classification Run
          </button>
          <button type="button" className="primary-button" onClick={openScoringModal}>
            New Scoring Run
          </button>
        </div>
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
        {runLaunchMessage ? <p className="success-callout">{runLaunchMessage}</p> : null}
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

      {showClassificationModal ? (
        <DetailModal
          title="New Classification Run"
          subtitle="Queue a batch classification run from the runs page"
          onClose={() => setShowClassificationModal(false)}
        >
          <form className="editor-form" onSubmit={handleClassificationSubmit}>
            <div className="inline-form-grid">
              <label>
                Limit
                <input
                  type="number"
                  min="1"
                  max="500"
                  value={classificationForm.limit}
                  onChange={(event) => setClassificationForm((current) => ({ ...current, limit: event.target.value }))}
                  required
                />
              </label>

              <label>
                Source
                <input
                  type="text"
                  value={classificationForm.source}
                  onChange={(event) => setClassificationForm((current) => ({ ...current, source: event.target.value }))}
                  placeholder="linkedin"
                />
              </label>

              <label>
                Classification Key
                <input
                  type="text"
                  value={classificationForm.classification_key}
                  onChange={(event) =>
                    setClassificationForm((current) => ({ ...current, classification_key: event.target.value }))
                  }
                  placeholder="Product Manager"
                />
              </label>

              <label>
                Prompt Key
                <input
                  type="text"
                  value={classificationForm.prompt_key}
                  onChange={(event) => setClassificationForm((current) => ({ ...current, prompt_key: event.target.value }))}
                  placeholder="classifier-v1"
                />
              </label>
            </div>

            <label>
              Callback URL
              <input
                type="url"
                value={classificationForm.callback_url}
                onChange={(event) => setClassificationForm((current) => ({ ...current, callback_url: event.target.value }))}
                placeholder="https://example.com/callback"
              />
            </label>

            <div className="checkbox-row">
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={classificationForm.force}
                  onChange={(event) => setClassificationForm((current) => ({ ...current, force: event.target.checked }))}
                />
                Force reclassification
              </label>
            </div>

            {classificationSubmitError ? <p className="error-callout">{classificationSubmitError}</p> : null}

            <div className="form-actions">
              <button type="submit" className="primary-button" disabled={classificationSubmitting}>
                {classificationSubmitting ? "Queueing..." : "Queue Classification Run"}
              </button>
              <button type="button" className="secondary-button" onClick={() => setShowClassificationModal(false)}>
                Cancel
              </button>
            </div>
          </form>
        </DetailModal>
      ) : null}

      {showScoringModal ? (
        <DetailModal
          title="New Scoring Run"
          subtitle="Queue an application scoring batch from the runs page"
          onClose={() => setShowScoringModal(false)}
        >
          <form className="editor-form" onSubmit={handleScoringSubmit}>
            <div className="inline-form-grid">
              <label>
                Limit
                <input
                  type="number"
                  min="1"
                  max="500"
                  value={scoringForm.limit}
                  onChange={(event) => setScoringForm((current) => ({ ...current, limit: event.target.value }))}
                  required
                />
              </label>

              <label>
                Status
                <input
                  type="text"
                  value={scoringForm.status}
                  onChange={(event) => setScoringForm((current) => ({ ...current, status: event.target.value }))}
                  placeholder="new"
                  required
                />
              </label>

              <label>
                User ID
                <input
                  type="number"
                  min="1"
                  value={scoringForm.user_id}
                  onChange={(event) => setScoringForm((current) => ({ ...current, user_id: event.target.value }))}
                  placeholder="1"
                />
              </label>

              <label>
                Resume ID
                <input
                  type="number"
                  min="1"
                  value={scoringForm.resume_id}
                  onChange={(event) => setScoringForm((current) => ({ ...current, resume_id: event.target.value }))}
                  placeholder="12"
                />
              </label>

              <label>
                Job Posting ID
                <input
                  type="number"
                  min="1"
                  value={scoringForm.job_posting_id}
                  onChange={(event) => setScoringForm((current) => ({ ...current, job_posting_id: event.target.value }))}
                  placeholder="345"
                />
              </label>

              <label>
                Classification Key
                <input
                  type="text"
                  value={scoringForm.classification_key}
                  onChange={(event) => setScoringForm((current) => ({ ...current, classification_key: event.target.value }))}
                  placeholder="Product Manager"
                />
              </label>

              <label>
                Prompt Key
                <input
                  type="text"
                  value={scoringForm.prompt_key}
                  onChange={(event) => setScoringForm((current) => ({ ...current, prompt_key: event.target.value }))}
                  placeholder="application_scoring"
                />
              </label>
            </div>

            <label>
              Callback URL
              <input
                type="url"
                value={scoringForm.callback_url}
                onChange={(event) => setScoringForm((current) => ({ ...current, callback_url: event.target.value }))}
                placeholder="https://example.com/callback"
              />
            </label>

            <div className="checkbox-row">
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={scoringForm.force}
                  onChange={(event) => setScoringForm((current) => ({ ...current, force: event.target.checked }))}
                />
                Force rescoring
              </label>
            </div>

            {scoringSubmitError ? <p className="error-callout">{scoringSubmitError}</p> : null}

            <div className="form-actions">
              <button type="submit" className="primary-button" disabled={scoringSubmitting}>
                {scoringSubmitting ? "Queueing..." : "Queue Scoring Run"}
              </button>
              <button type="button" className="secondary-button" onClick={() => setShowScoringModal(false)}>
                Cancel
              </button>
            </div>
          </form>
        </DetailModal>
      ) : null}
    </section>
  );
}
