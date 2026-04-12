import { useState } from "react";

import { getApplication, pasteJob } from "../api";
import { ApplicationDetailModal } from "../components/ApplicationDetailModal";
import type { JobApplication, OnboardingStatusResponse, PasteJobResponse } from "../types";
import { renderListish } from "../utils";

interface PasteJobPageProps {
  onboardingStatus: OnboardingStatusResponse | null;
}

const EMPTY_FORM = {
  url: "",
  company_name: "",
  title: "",
  location: "",
  description: "",
};

export function PasteJobPage({ onboardingStatus }: PasteJobPageProps) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<PasteJobResponse | null>(null);
  const [application, setApplication] = useState<JobApplication | null>(null);
  const [selectedApplicationId, setSelectedApplicationId] = useState<number | null>(null);

  async function pollApplication(applicationId: number) {
    setPolling(true);
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const latest = await getApplication(applicationId);
      setApplication(latest);
      if (latest.scored_at || latest.score_error) {
        setPolling(false);
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 3000));
    }
    setPolling(false);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setResponse(null);
    setApplication(null);

    try {
      const result = await pasteJob({
        input_type: form.url.trim() ? "url" : "description",
        url: form.url.trim() || null,
        company_name: form.company_name.trim() || null,
        title: form.title.trim() || null,
        location: form.location.trim() || null,
        description: form.description.trim() || null,
        process_now: true,
        mode: "async",
      });
      setResponse(result);
      setApplication(result.application);
      if (result.run_ids.length > 0) {
        void pollApplication(result.application.id);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to process this job.");
    } finally {
      setSubmitting(false);
    }
  }

  const providerLabel = onboardingStatus?.settings.provider.provider_mode === "configure_later"
    ? "Configure later"
    : onboardingStatus?.settings.provider.provider_name ?? "AI provider";

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Job fit</p>
          <h2>Paste a job</h2>
          <p className="page-subtitle">Paste the job description, add the URL if you have it, then get a fit score and recommendation.</p>
        </div>
        <div className="page-actions">
          <div className="stat-chip">{onboardingStatus?.default_resume?.name ?? "Resume ready"}</div>
          <div className="stat-chip">{providerLabel}</div>
        </div>
      </div>

      <div className="panel detail-panel">
        <form className="editor-form" onSubmit={handleSubmit}>
          <div className="inline-form-grid">
            <label>
              Job URL
              <input
                type="url"
                value={form.url}
                onChange={(event) => setForm((current) => ({ ...current, url: event.target.value }))}
                placeholder="https://example.com/jobs/123"
              />
            </label>

            <label>
              Company
              <input
                type="text"
                value={form.company_name}
                onChange={(event) => setForm((current) => ({ ...current, company_name: event.target.value }))}
                placeholder="Company name"
              />
            </label>

            <label>
              Role
              <input
                type="text"
                value={form.title}
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                placeholder="Role title"
              />
            </label>

            <label>
              Location
              <input
                type="text"
                value={form.location}
                onChange={(event) => setForm((current) => ({ ...current, location: event.target.value }))}
                placeholder="Remote, New York, Hybrid"
              />
            </label>
          </div>

          <label>
            Job Description
            <textarea
              className="editor-textarea"
              value={form.description}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              placeholder="Paste the job description here"
              required
            />
          </label>

          {error ? <p className="error-callout">{error}</p> : null}

          <div className="form-actions">
            <button type="submit" className="primary-button" disabled={submitting}>
              {submitting ? "Starting..." : "Get Recommendation"}
            </button>
          </div>
        </form>
      </div>

      {response || application ? (
        <div className="panel detail-panel result-panel">
          <div className="page-header">
            <div>
              <p className="eyebrow">Recommendation</p>
              <h3>{application?.recommendation ?? (polling ? "Processing" : "Saved")}</h3>
              <p className="page-subtitle">
                {response?.message ?? (polling ? "Classification and scoring are running in the background." : "Open the result for full details.")}
              </p>
            </div>
            {application ? (
              <button type="button" className="secondary-button" onClick={() => setSelectedApplicationId(application.id)}>
                Open Details
              </button>
            ) : null}
          </div>

          {application ? (
            <dl className="detail-list">
              <div>
                <dt>Job fit</dt>
                <dd>{application.score ?? "Pending"}</dd>
              </div>
              <div>
                <dt>Screening likelihood</dt>
                <dd>{application.screening_likelihood ?? "Pending"}</dd>
              </div>
              <div>
                <dt>Role classification</dt>
                <dd>{application.classification_key ?? "Pending"}</dd>
              </div>
              <div>
                <dt>Strengths</dt>
                <dd>{renderListish(application.strengths) || "Pending"}</dd>
              </div>
              <div>
                <dt>Gaps</dt>
                <dd>{renderListish(application.gaps) || "Pending"}</dd>
              </div>
            </dl>
          ) : null}
        </div>
      ) : null}

      {selectedApplicationId ? (
        <ApplicationDetailModal
          applicationId={selectedApplicationId}
          fallbackTitle={application?.title ?? "Job"}
          fallbackSubtitle={`Application #${selectedApplicationId}`}
          onClose={() => setSelectedApplicationId(null)}
          onApplicationUpdated={setApplication}
        />
      ) : null}
    </section>
  );
}
