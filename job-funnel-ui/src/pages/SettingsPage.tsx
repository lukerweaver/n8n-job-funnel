import { useEffect, useState } from "react";

import { getSettings, updateSettings } from "../api";
import type { AppSettings } from "../types";

interface SettingsPageProps {
  onSettingsUpdated?: (settings: AppSettings) => void;
}

const DEFAULT_FORM = {
  profile_name: "",
  target_roles: "",
  keywords: "",
  location_preference: "",
  salary_preference: "",
  provider_mode: "configure_later" as "ollama" | "hosted" | "configure_later",
  provider_name: "",
  provider_base_url: "",
  provider_model: "",
  provider_api_key: "",
  auto_process_jobs: true,
  unprocessed_jobs_threshold: "5",
  minutes_since_last_run_threshold: "60",
  advanced_mode_enabled: false,
  n8n_webhook_url: "",
};

function listToText(value: string[] | null) {
  return value?.join(", ") ?? "";
}

function splitList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function toForm(settings: AppSettings) {
  const automation = settings.automation_settings ?? {};
  return {
    profile_name: settings.profile_name ?? "",
    target_roles: listToText(settings.target_roles),
    keywords: listToText(settings.keywords),
    location_preference: settings.location_preference ?? "",
    salary_preference: settings.salary_preference ?? "",
    provider_mode: settings.provider.provider_mode as "ollama" | "hosted" | "configure_later",
    provider_name: settings.provider.provider_name ?? "",
    provider_base_url: settings.provider.provider_base_url ?? "",
    provider_model: settings.provider.provider_model ?? "",
    provider_api_key: "",
    auto_process_jobs: automation.auto_process_jobs !== false,
    unprocessed_jobs_threshold: String(automation.unprocessed_jobs_threshold ?? "5"),
    minutes_since_last_run_threshold: String(automation.minutes_since_last_run_threshold ?? "60"),
    advanced_mode_enabled: settings.advanced_mode_enabled,
    n8n_webhook_url: settings.n8n_webhook_url ?? "",
  };
}

export function SettingsPage({ onSettingsUpdated }: SettingsPageProps) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSettings()
      .then((response) => {
        if (cancelled) {
          return;
        }
        setSettings(response);
        setForm(toForm(response));
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
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);

    try {
      const updated = await updateSettings({
        profile_name: form.profile_name.trim() || null,
        target_roles: splitList(form.target_roles),
        keywords: splitList(form.keywords),
        location_preference: form.location_preference.trim() || null,
        salary_preference: form.salary_preference.trim() || null,
        provider: {
          provider_mode: form.provider_mode,
          provider_name: form.provider_name.trim() || (form.provider_mode === "hosted" ? "openai_compatible" : null),
          provider_base_url: form.provider_base_url.trim() || null,
          provider_model: form.provider_model.trim() || null,
          provider_api_key: form.provider_api_key.trim() || undefined,
        },
        automation_settings: {
          auto_process_jobs: form.auto_process_jobs,
          unprocessed_jobs_threshold: Number(form.unprocessed_jobs_threshold || "5"),
          minutes_since_last_run_threshold: Number(form.minutes_since_last_run_threshold || "60"),
          opportunistic_trigger_enabled: true,
        },
        advanced_mode_enabled: form.advanced_mode_enabled,
        n8n_webhook_url: form.n8n_webhook_url.trim() || null,
      });
      setSettings(updated);
      setForm(toForm(updated));
      onSettingsUpdated?.(updated);
      setMessage("Settings saved.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unable to save settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h2>Profile and AI provider</h2>
          <p className="page-subtitle">Keep the simple path ready. Advanced controls stay collapsed by default.</p>
        </div>
        {settings ? <div className="stat-chip">{settings.provider.has_api_key ? "API key saved" : "No API key saved"}</div> : null}
      </div>

      <div className="panel detail-panel">
        {loading ? <p className="state-message">Loading settings...</p> : null}
        {error ? <p className="error-callout">{error}</p> : null}
        {message ? <p className="success-callout">{message}</p> : null}

        {!loading ? (
          <form className="editor-form" onSubmit={handleSubmit}>
            <div className="inline-form-grid">
              <label>
                Profile Name
                <input value={form.profile_name} onChange={(event) => setForm((current) => ({ ...current, profile_name: event.target.value }))} />
              </label>
              <label>
                Target Roles
                <input value={form.target_roles} onChange={(event) => setForm((current) => ({ ...current, target_roles: event.target.value }))} />
              </label>
              <label>
                Keywords
                <input value={form.keywords} onChange={(event) => setForm((current) => ({ ...current, keywords: event.target.value }))} />
              </label>
              <label>
                Location / Remote
                <input value={form.location_preference} onChange={(event) => setForm((current) => ({ ...current, location_preference: event.target.value }))} />
              </label>
              <label>
                Salary Preference
                <input value={form.salary_preference} onChange={(event) => setForm((current) => ({ ...current, salary_preference: event.target.value }))} />
              </label>
              <label>
                AI Provider
                <select
                  value={form.provider_mode}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, provider_mode: event.target.value as "ollama" | "hosted" | "configure_later" }))
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
                {form.provider_mode === "hosted" ? (
                  <label>
                    Provider
                    <input value={form.provider_name} onChange={(event) => setForm((current) => ({ ...current, provider_name: event.target.value }))} placeholder="openai_compatible" />
                  </label>
                ) : null}
                <label>
                  Provider URL
                  <input value={form.provider_base_url} onChange={(event) => setForm((current) => ({ ...current, provider_base_url: event.target.value }))} />
                </label>
                <label>
                  Model
                  <input value={form.provider_model} onChange={(event) => setForm((current) => ({ ...current, provider_model: event.target.value }))} />
                </label>
                {form.provider_mode === "hosted" ? (
                  <label>
                    API Key
                    <input type="password" value={form.provider_api_key} onChange={(event) => setForm((current) => ({ ...current, provider_api_key: event.target.value }))} placeholder={settings?.provider.has_api_key ? "Saved. Enter a new key to replace." : "sk-..."} />
                  </label>
                ) : null}
              </div>
            ) : null}

            <details className="advanced-details" open={form.advanced_mode_enabled}>
              <summary>Advanced settings</summary>
              <div className="inline-form-grid">
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={form.auto_process_jobs}
                    onChange={(event) => setForm((current) => ({ ...current, auto_process_jobs: event.target.checked }))}
                  />
                  Auto-process jobs
                </label>
                <label>
                  Unprocessed Jobs Threshold
                  <input type="number" value={form.unprocessed_jobs_threshold} onChange={(event) => setForm((current) => ({ ...current, unprocessed_jobs_threshold: event.target.value }))} />
                </label>
                <label>
                  Minutes Since Last Run
                  <input type="number" value={form.minutes_since_last_run_threshold} onChange={(event) => setForm((current) => ({ ...current, minutes_since_last_run_threshold: event.target.value }))} />
                </label>
                <label>
                  n8n Webhook URL
                  <input value={form.n8n_webhook_url} onChange={(event) => setForm((current) => ({ ...current, n8n_webhook_url: event.target.value }))} />
                </label>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={form.advanced_mode_enabled}
                    onChange={(event) => setForm((current) => ({ ...current, advanced_mode_enabled: event.target.checked }))}
                  />
                  Show advanced navigation
                </label>
              </div>
            </details>

            <div className="form-actions">
              <button type="submit" className="primary-button" disabled={saving}>
                {saving ? "Saving..." : "Save Settings"}
              </button>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}
