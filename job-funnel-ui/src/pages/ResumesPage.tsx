import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { createResume, getResumes, updateResume } from "../api";
import { DetailModal } from "../components/DetailModal";
import { PaginationControls } from "../components/PaginationControls";
import type { Resume } from "../types";
import { formatDate } from "../utils";

const DEFAULT_LIMIT = 25;

interface ResumeFormState {
  user_id: string;
  name: string;
  prompt_key: string;
  classification_key: string;
  content: string;
  is_active: boolean;
  is_default: boolean;
}

const EMPTY_FORM: ResumeFormState = {
  user_id: "1",
  name: "",
  prompt_key: "",
  classification_key: "",
  content: "",
  is_active: true,
  is_default: false,
};

function toFormState(resume: Resume): ResumeFormState {
  return {
    user_id: String(resume.user_id),
    name: resume.name,
    prompt_key: resume.prompt_key,
    classification_key: resume.classification_key ?? "",
    content: resume.content,
    is_active: resume.is_active,
    is_default: resume.is_default,
  };
}

export function ResumesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<Resume[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Resume | null>(null);
  const [editing, setEditing] = useState<Resume | null>(null);
  const [form, setForm] = useState<ResumeFormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

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

    getResumes(params)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setData(response.items);
        setTotal(response.total);
        setSelected((current) => (current ? response.items.find((item) => item.id === current.id) ?? null : null));
        setEditing((current) => (current ? response.items.find((item) => item.id === current.id) ?? null : null));
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

  useEffect(() => {
    if (editing) {
      setForm(toFormState(editing));
      setSubmitError(null);
      return;
    }
    setForm(EMPTY_FORM);
    setSubmitError(null);
  }, [editing]);

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
      offset: "0",
    });
  }

  function startNewResume() {
    setEditing({} as Resume);
    setForm(EMPTY_FORM);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);

    const payload = {
      user_id: Number(form.user_id),
      name: form.name.trim(),
      prompt_key: form.prompt_key.trim() || null,
      classification_key: form.classification_key.trim() || null,
      content: form.content,
      is_active: form.is_active,
      is_default: form.is_default,
    };

    try {
      if (editing && "id" in editing) {
        await updateResume(editing.id, {
          name: payload.name,
          prompt_key: payload.prompt_key,
          classification_key: payload.classification_key,
          content: payload.content,
          is_active: payload.is_active,
          is_default: payload.is_default,
        });
      } else {
        await createResume(payload);
      }

      setEditing(null);
      const next = new URLSearchParams(params);
      setSearchParams(next);
    } catch (requestError) {
      setSubmitError(requestError instanceof Error ? requestError.message : "Unable to save resume.");
    } finally {
      setSubmitting(false);
    }
  }

  const limit = Number(params.get("limit") ?? String(DEFAULT_LIMIT));
  const offset = Number(params.get("offset") ?? "0");
  const selectedIndex = selected ? data.findIndex((item) => item.id === selected.id) : -1;

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
          <p className="eyebrow">Page 4</p>
          <h2>Resumes</h2>
          <p className="page-subtitle">Browse active/default resume variants and inspect full resume content on demand.</p>
        </div>
        <div className="page-actions">
          <div className="stat-chip">{total} visible resumes</div>
          <button type="button" className="primary-button" onClick={startNewResume}>
            New Resume
          </button>
        </div>
      </div>

      <div className="panel filter-panel">
        <div className="filter-grid">
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
            Classification
            <input
              type="text"
              value={params.get("classification_key") ?? ""}
              onChange={(event) => updateParam("classification_key", event.target.value)}
              placeholder="product_manager"
            />
          </label>

          <label>
            Active State
            <select value={params.get("is_active") ?? ""} onChange={(event) => updateParam("is_active", event.target.value)}>
              <option value="">All</option>
              <option value="true">active</option>
              <option value="false">inactive</option>
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
        {loading ? <p className="state-message">Loading resumes...</p> : null}
        {error ? <p className="state-message error-message">{error}</p> : null}
        {!loading && !error && data.length === 0 ? <p className="state-message">No resumes match current filters.</p> : null}

        {!loading && !error && data.length > 0 ? (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>User</th>
                  <th>Prompt</th>
                  <th>Classification</th>
                  <th>Default</th>
                  <th>State</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.map((resume) => (
                  <tr key={resume.id} onClick={() => setSelected(resume)}>
                    <td>{resume.name}</td>
                    <td className="mono">{resume.user_id}</td>
                    <td>{resume.prompt_key}</td>
                    <td>{resume.classification_key ?? "N/A"}</td>
                    <td>{resume.is_default ? "yes" : "no"}</td>
                    <td>
                      <span className={`status-pill ${resume.is_active ? "status-completed" : "status-skipped"}`}>
                        {resume.is_active ? "active" : "inactive"}
                      </span>
                    </td>
                    <td>{formatDate(resume.updated_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditing(resume);
                        }}
                      >
                        Edit
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
        <DetailModal
          title={selected.name}
          subtitle={`Resume #${selected.id} · user ${selected.user_id}`}
          onClose={() => setSelected(null)}
          onPrevious={() => setSelected(data[selectedIndex - 1])}
          onNext={() => setSelected(data[selectedIndex + 1])}
          previousDisabled={selectedIndex <= 0}
          nextDisabled={selectedIndex === -1 || selectedIndex >= data.length - 1}
        >
          <div className="detail-section">
            <h4>Metadata</h4>
            <dl className="detail-list">
              <div>
                <dt>Prompt Key</dt>
                <dd>{selected.prompt_key}</dd>
              </div>
              <div>
                <dt>Classification</dt>
                <dd>{selected.classification_key ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Default</dt>
                <dd>{selected.is_default ? "Yes" : "No"}</dd>
              </div>
              <div>
                <dt>State</dt>
                <dd>{selected.is_active ? "Active" : "Inactive"}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{formatDate(selected.updated_at)}</dd>
              </div>
            </dl>
          </div>

          <div className="detail-section">
            <h4>Content</h4>
            <pre className="detail-pre">{selected.content}</pre>
          </div>
        </DetailModal>
      ) : null}

      {editing ? (
        <DetailModal
          title={"id" in editing ? `Edit ${editing.name}` : "New Resume"}
          subtitle={"id" in editing ? `Resume #${editing.id}` : "Create a new resume variant"}
          onClose={() => setEditing(null)}
        >
          <form className="editor-form" onSubmit={handleSubmit}>
            <div className="inline-form-grid">
              <label>
                User ID
                <input
                  type="number"
                  value={form.user_id}
                  onChange={(event) => setForm((current) => ({ ...current, user_id: event.target.value }))}
                  required
                />
              </label>

              <label>
                Name
                <input
                  type="text"
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  required
                />
              </label>

              <label>
                Prompt Key
                <input
                  type="text"
                  value={form.prompt_key}
                  onChange={(event) => setForm((current) => ({ ...current, prompt_key: event.target.value }))}
                  placeholder="default_resume"
                />
              </label>

              <label>
                Classification Key
                <input
                  type="text"
                  value={form.classification_key}
                  onChange={(event) => setForm((current) => ({ ...current, classification_key: event.target.value }))}
                  placeholder="product_manager"
                />
              </label>
            </div>

            <label>
              Resume Content
              <textarea
                className="editor-textarea"
                value={form.content}
                onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))}
                required
              />
            </label>

            <div className="checkbox-row">
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
                />
                Active
              </label>

              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={form.is_default}
                  onChange={(event) => setForm((current) => ({ ...current, is_default: event.target.checked }))}
                />
                Default
              </label>
            </div>

            {submitError ? <p className="error-callout">{submitError}</p> : null}

            <div className="form-actions">
              <button type="submit" className="primary-button" disabled={submitting}>
                {submitting ? "Saving..." : "id" in editing ? "Update Resume" : "Create Resume"}
              </button>
              <button type="button" className="secondary-button" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </div>
          </form>
        </DetailModal>
      ) : null}
    </section>
  );
}
