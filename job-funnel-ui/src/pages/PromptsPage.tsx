import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { createPromptLibrary, deletePromptLibrary, getPromptLibrary, updatePromptLibrary } from "../api";
import { DetailModal } from "../components/DetailModal";
import { PaginationControls } from "../components/PaginationControls";
import type { PromptLibrary } from "../types";

const DEFAULT_LIMIT = 25;

interface PromptFormState {
  prompt_key: string;
  prompt_type: string;
  prompt_version: string;
  system_prompt: string;
  user_prompt_template: string;
  context: string;
  max_tokens: string;
  temperature: string;
  is_active: boolean;
}

const EMPTY_FORM: PromptFormState = {
  prompt_key: "",
  prompt_type: "scoring",
  prompt_version: "1",
  system_prompt: "",
  user_prompt_template: "",
  context: "",
  max_tokens: "",
  temperature: "",
  is_active: true,
};

function toFormState(prompt: PromptLibrary): PromptFormState {
  return {
    prompt_key: prompt.prompt_key,
    prompt_type: prompt.prompt_type,
    prompt_version: String(prompt.prompt_version),
    system_prompt: prompt.system_prompt,
    user_prompt_template: prompt.user_prompt_template,
    context: prompt.context ?? "",
    max_tokens: prompt.max_tokens == null ? "" : String(prompt.max_tokens),
    temperature: prompt.temperature == null ? "" : String(prompt.temperature),
    is_active: prompt.is_active,
  };
}

export function PromptsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<PromptLibrary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<PromptLibrary | null>(null);
  const [editing, setEditing] = useState<PromptLibrary | null>(null);
  const [form, setForm] = useState<PromptFormState>(EMPTY_FORM);
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

    getPromptLibrary(params)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setData(response.items);
        setTotal(response.total);
        setSelected((current) => (current ? response.items.find((item) => item.id === current.id) ?? null : null));
        setEditing((current) => (current ? response.items.find((item) => item.id === current.id) ?? null : current));
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

  function startNewPrompt() {
    setEditing(null);
    setForm(EMPTY_FORM);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);

    const payload = {
      prompt_key: form.prompt_key.trim(),
      prompt_type: form.prompt_type.trim(),
      prompt_version: Number(form.prompt_version),
      system_prompt: form.system_prompt,
      user_prompt_template: form.user_prompt_template,
      context: form.context.trim() || null,
      max_tokens: form.max_tokens.trim() ? Number(form.max_tokens) : null,
      temperature: form.temperature.trim() ? Number(form.temperature) : null,
      is_active: form.is_active,
    };

    try {
      if (editing) {
        await updatePromptLibrary(editing.id, payload);
      } else {
        await createPromptLibrary(payload);
      }

      const refreshParams = new URLSearchParams(params);
      setSearchParams(refreshParams);
      setEditing(null);
      setForm(EMPTY_FORM);
    } catch (requestError) {
      setSubmitError(requestError instanceof Error ? requestError.message : "Unable to save prompt.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(promptId: number) {
    const confirmed = window.confirm("Delete this prompt version?");
    if (!confirmed) {
      return;
    }

    setSubmitError(null);

    try {
      await deletePromptLibrary(promptId);
      if (selected?.id === promptId) {
        setSelected(null);
      }
      if (editing?.id === promptId) {
        setEditing(null);
      }
      const refreshParams = new URLSearchParams(params);
      setSearchParams(refreshParams);
    } catch (requestError) {
      setSubmitError(requestError instanceof Error ? requestError.message : "Unable to delete prompt.");
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
          <p className="eyebrow">Page 5</p>
          <h2>Prompt Library</h2>
          <p className="page-subtitle">Track scoring and classification prompt versions, then edit the active variants in place.</p>
        </div>
        <div className="page-actions">
          <div className="stat-chip">{total} visible prompts</div>
          <button type="button" className="primary-button" onClick={startNewPrompt}>
            New Prompt
          </button>
        </div>
      </div>

      <div className="panel filter-panel">
        <div className="filter-grid">
          <label>
            Prompt Key
            <input
              type="text"
              value={params.get("prompt_key") ?? ""}
              onChange={(event) => updateParam("prompt_key", event.target.value)}
              placeholder="application_scoring"
            />
          </label>

          <label>
            Prompt Type
            <input
              type="text"
              value={params.get("prompt_type") ?? ""}
              onChange={(event) => updateParam("prompt_type", event.target.value)}
              placeholder="scoring"
            />
          </label>

          <label>
            Version
            <input
              type="number"
              value={params.get("prompt_version") ?? ""}
              onChange={(event) => updateParam("prompt_version", event.target.value)}
              placeholder="3"
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

      <div className="split-layout">
        <div className="panel form-panel">
          <div className="form-header">
            <div>
              <p className="eyebrow">{editing ? "Editing" : "Create"}</p>
              <h3>{editing ? `${editing.prompt_key} v${editing.prompt_version}` : "New Prompt"}</h3>
            </div>
          </div>

          <form className="editor-form" onSubmit={handleSubmit}>
            <div className="inline-form-grid">
              <label>
                Prompt Key
                <input
                  type="text"
                  value={form.prompt_key}
                  onChange={(event) => setForm((current) => ({ ...current, prompt_key: event.target.value }))}
                  required
                />
              </label>

              <label>
                Prompt Type
                <input
                  type="text"
                  value={form.prompt_type}
                  onChange={(event) => setForm((current) => ({ ...current, prompt_type: event.target.value }))}
                  required
                />
              </label>

              <label>
                Version
                <input
                  type="number"
                  value={form.prompt_version}
                  onChange={(event) => setForm((current) => ({ ...current, prompt_version: event.target.value }))}
                  min="1"
                  required
                />
              </label>

              <label>
                Max Tokens
                <input
                  type="number"
                  value={form.max_tokens}
                  onChange={(event) => setForm((current) => ({ ...current, max_tokens: event.target.value }))}
                  placeholder="1200"
                />
              </label>

              <label>
                Temperature
                <input
                  type="number"
                  step="0.1"
                  value={form.temperature}
                  onChange={(event) => setForm((current) => ({ ...current, temperature: event.target.value }))}
                  placeholder="0.2"
                />
              </label>
            </div>

            <label>
              System Prompt
              <textarea
                className="editor-textarea"
                value={form.system_prompt}
                onChange={(event) => setForm((current) => ({ ...current, system_prompt: event.target.value }))}
                required
              />
            </label>

            <label>
              User Prompt Template
              <textarea
                className="editor-textarea"
                value={form.user_prompt_template}
                onChange={(event) => setForm((current) => ({ ...current, user_prompt_template: event.target.value }))}
                required
              />
            </label>

            <label>
              Context
              <textarea
                className="editor-textarea editor-textarea-compact"
                value={form.context}
                onChange={(event) => setForm((current) => ({ ...current, context: event.target.value }))}
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
            </div>

            {submitError ? <p className="error-callout">{submitError}</p> : null}

            <div className="form-actions">
              <button type="submit" className="primary-button" disabled={submitting}>
                {submitting ? "Saving..." : editing ? "Update Prompt" : "Create Prompt"}
              </button>
              {editing ? (
                <>
                  <button type="button" className="secondary-button" onClick={startNewPrompt}>
                    Cancel Edit
                  </button>
                  <button type="button" className="ghost-button danger-button" onClick={() => handleDelete(editing.id)}>
                    Delete
                  </button>
                </>
              ) : null}
            </div>
          </form>
        </div>

        <div className="panel table-panel">
          {loading ? <p className="state-message">Loading prompts...</p> : null}
          {error ? <p className="state-message error-message">{error}</p> : null}
          {!loading && !error && data.length === 0 ? <p className="state-message">No prompts match current filters.</p> : null}

          {!loading && !error && data.length > 0 ? (
            <>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Type</th>
                    <th>Version</th>
                    <th>Active</th>
                    <th>Max Tokens</th>
                    <th>Temperature</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.map((prompt) => (
                    <tr key={prompt.id} onClick={() => setSelected(prompt)}>
                      <td>{prompt.prompt_key}</td>
                      <td>{prompt.prompt_type}</td>
                      <td className="mono">v{prompt.prompt_version}</td>
                      <td>
                        <span className={`status-pill ${prompt.is_active ? "status-completed" : "status-skipped"}`}>
                          {prompt.is_active ? "active" : "inactive"}
                        </span>
                      </td>
                      <td>{prompt.max_tokens ?? "N/A"}</td>
                      <td>{prompt.temperature ?? "N/A"}</td>
                      <td>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setEditing(prompt);
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
      </div>

      {selected ? (
        <DetailModal
          title={`${selected.prompt_key} v${selected.prompt_version}`}
          subtitle={`${selected.prompt_type} prompt`}
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
                <dt>Active</dt>
                <dd>{selected.is_active ? "Yes" : "No"}</dd>
              </div>
              <div>
                <dt>Max Tokens</dt>
                <dd>{selected.max_tokens ?? "N/A"}</dd>
              </div>
              <div>
                <dt>Temperature</dt>
                <dd>{selected.temperature ?? "N/A"}</dd>
              </div>
            </dl>
          </div>

          <div className="detail-section">
            <h4>System Prompt</h4>
            <pre className="detail-pre">{selected.system_prompt}</pre>
          </div>

          <div className="detail-section">
            <h4>User Prompt Template</h4>
            <pre className="detail-pre">{selected.user_prompt_template}</pre>
          </div>

          {selected.context ? (
            <div className="detail-section">
              <h4>Context</h4>
              <pre className="detail-pre">{selected.context}</pre>
            </div>
          ) : null}
        </DetailModal>
      ) : null}
    </section>
  );
}
