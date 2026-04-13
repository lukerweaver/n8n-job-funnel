import { NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";

import { getOnboardingStatus } from "./api";
import { ActiveApplicationsPage } from "./pages/ActiveApplicationsPage";
import { ApplicationStatisticsPage } from "./pages/ApplicationStatisticsPage";
import { ApplicationsPage } from "./pages/ApplicationsPage";
import { HistoricalApplicationsPage } from "./pages/HistoricalApplicationsPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { PasteJobPage } from "./pages/PasteJobPage";
import { PromptsPage } from "./pages/PromptsPage";
import { ResumesPage } from "./pages/ResumesPage";
import { RunResultsPage } from "./pages/RunResultsPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StatisticsPage } from "./pages/StatisticsPage";
import type { OnboardingStatusResponse } from "./types";

export function App() {
  const [onboardingStatus, setOnboardingStatus] = useState<OnboardingStatusResponse | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getOnboardingStatus()
      .then((response) => {
        if (!cancelled) {
          setOnboardingStatus(response);
        }
      })
      .catch((requestError: Error) => {
        if (!cancelled) {
          setStatusError(requestError.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingStatus(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (loadingStatus) {
    return <main className="onboarding-shell"><p className="state-message">Loading job fit...</p></main>;
  }

  if (statusError) {
    return <main className="onboarding-shell"><p className="error-callout">{statusError}</p></main>;
  }

  if (!onboardingStatus?.completed) {
    return <OnboardingPage onCompleted={setOnboardingStatus} />;
  }

  const advancedMode = onboardingStatus.settings.advanced_mode_enabled;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">Job Funnel</p>
          <h1>Job Fit</h1>
          <p className="brand-copy">
            Paste jobs, compare them to your resume, and track recommendations.
          </p>
        </div>

        <nav className="nav">
          <NavLink className="nav-link" to="/">
            Paste Job
          </NavLink>
          <NavLink className="nav-link" to="/applications">
            Recommendation History
          </NavLink>
          <NavLink className="nav-link" to="/active-applications">
            Active Applications
          </NavLink>
          <NavLink className="nav-link" to="/historical-applications">
            Historical Applications
          </NavLink>
          <NavLink className="nav-link" to="/resumes">
            Resumes
          </NavLink>
          <NavLink className="nav-link" to="/settings">
            Settings
          </NavLink>
          {advancedMode ? (
            <>
              <NavLink className="nav-link" to="/runs">
                Runs
              </NavLink>
              <NavLink className="nav-link" to="/statistics">
                Job Posting Statistics
              </NavLink>
              <NavLink className="nav-link" to="/application-statistics">
                Job Application Statistics
              </NavLink>
              <NavLink className="nav-link" to="/prompts">
                Prompts
              </NavLink>
            </>
          ) : null}
        </nav>

        <div className="sidebar-note">
          <p>Advanced controls are available in Settings.</p>
        </div>
      </aside>

      <main className="workspace">
        <Routes>
          <Route path="/" element={<PasteJobPage onboardingStatus={onboardingStatus} />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/active-applications" element={<ActiveApplicationsPage />} />
          <Route path="/historical-applications" element={<HistoricalApplicationsPage />} />
          <Route
            path="/settings"
            element={
              <SettingsPage
                onSettingsUpdated={(settings) =>
                  setOnboardingStatus((current) => (current ? { ...current, settings } : current))
                }
              />
            }
          />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunResultsPage />} />
          <Route path="/statistics" element={<StatisticsPage />} />
          <Route path="/application-statistics" element={<ApplicationStatisticsPage />} />
          <Route path="/resumes" element={<ResumesPage />} />
          <Route path="/prompts" element={<PromptsPage />} />
        </Routes>
      </main>
    </div>
  );
}
