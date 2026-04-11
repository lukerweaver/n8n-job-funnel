import { useState } from "react";

import { completeOnboarding } from "../api";
import type { OnboardingStatusResponse } from "../types";

interface OnboardingPageProps {
  onCompleted: (status: OnboardingStatusResponse) => void;
}

const DEFAULT_FORM = {
  profile_name: "",
  resume_content: "",
  target_roles: "",
  keywords: "",
  location_preference: "",
  salary_preference: "",
  provider_mode: "configure_later" as "ollama" | "hosted" | "configure_later",
  provider_base_url: "",
  provider_api_key: "",
  provider_model: "",
};

function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function OnboardingPage({ onCompleted }: OnboardingPageProps) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const status = await completeOnboarding({
        profile_name: form.profile_name.trim(),
        resume_name: "Default Resume",
        resume_content: form.resume_content,
        target_roles: splitList(form.target_roles),
        keywords: splitList(form.keywords),
        location_preference: form.location_preference.trim() || null,
        salary_preference: form.salary_preference.trim() || null,
        provider: {
          provider_mode: form.provider_mode,
          provider_name: form.provider_mode === "hosted" ? "openai_compatible" : null,
          provider_base_url: form.provider_base_url.trim() || null,
          provider_api_key: form.provider_api_key.trim() || null,
          provider_model: form.provider_model.trim() || null,
        },
      });
      onCompleted(status);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to complete onboarding.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="onboarding-shell">
      <section className="onboarding-panel">
        <div className="page-header">
          <div>
            <p className="eyebrow">First run</p>
            <h1>Set up job fit</h1>
            <p className="stats-page-subtitle">Add your resume, target roles, and AI provider. You can change these later.</p>
          </div>
        </div>

        <form className="editor-form" onSubmit={handleSubmit}>
          <div className="inline-form-grid">
            <label>
              Profile Name
              <input
                type="text"
                value={form.profile_name}
                onChange={(event) => setForm((current) => ({ ...current, profile_name: event.target.value }))}
                placeholder="Alex"
                required
              />
            </label>

            <label>
              Target Roles
              <input
                type="text"
                value={form.target_roles}
                onChange={(event) => setForm((current) => ({ ...current, target_roles: event.target.value }))}
                placeholder="Product marketing, growth, lifecycle"
                required
              />
            </label>

            <label>
              Keywords
              <input
                type="text"
                value={form.keywords}
                onChange={(event) => setForm((current) => ({ ...current, keywords: event.target.value }))}
                placeholder="B2B, lifecycle, PLG"
              />
            </label>

            <label>
              Location / Remote
              <input
                type="text"
                value={form.location_preference}
                onChange={(event) => setForm((current) => ({ ...current, location_preference: event.target.value }))}
                placeholder="Remote, New York, hybrid"
              />
            </label>

            <label>
              Salary Preference
              <input
                type="text"
                value={form.salary_preference}
                onChange={(event) => setForm((current) => ({ ...current, salary_preference: event.target.value }))}
                placeholder="$140k+"
              />
            </label>

            <label>
              AI Provider
              <select
                value={form.provider_mode}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    provider_mode: event.target.value as "ollama" | "hosted" | "configure_later",
                  }))
                }
              >
                <option value="configure_later">Configure later</option>
                <option value="ollama">Local (Ollama)</option>
                <option value="hosted">Hosted (API key)</option>
              </select>
            </label>
          </div>

          {form.provider_mode !== "configure_later" ? (
            <div className="inline-form-grid">
              <label>
                Provider URL
                <input
                  type="text"
                  value={form.provider_base_url}
                  onChange={(event) => setForm((current) => ({ ...current, provider_base_url: event.target.value }))}
                  placeholder={form.provider_mode === "ollama" ? "http://localhost:11434" : "https://api.openai.com/v1"}
                />
              </label>

              <label>
                Model
                <input
                  type="text"
                  value={form.provider_model}
                  onChange={(event) => setForm((current) => ({ ...current, provider_model: event.target.value }))}
                  placeholder={form.provider_mode === "ollama" ? "qwen2.5:14b-instruct" : "gpt-4.1-mini"}
                />
              </label>

              {form.provider_mode === "hosted" ? (
                <label>
                  API Key
                  <input
                    type="password"
                    value={form.provider_api_key}
                    onChange={(event) => setForm((current) => ({ ...current, provider_api_key: event.target.value }))}
                    placeholder="sk-..."
                  />
                </label>
              ) : null}
            </div>
          ) : null}

          <label>
            Resume
            <textarea
              className="editor-textarea"
              value={form.resume_content}
              onChange={(event) => setForm((current) => ({ ...current, resume_content: event.target.value }))}
              placeholder="Paste your resume here"
              required
            />
          </label>

          {error ? <p className="error-callout">{error}</p> : null}

          <div className="form-actions">
            <button type="submit" className="primary-button" disabled={submitting}>
              {submitting ? "Saving..." : "Start"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
