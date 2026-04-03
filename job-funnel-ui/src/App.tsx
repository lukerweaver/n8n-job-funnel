import { NavLink, Route, Routes } from "react-router-dom";

import { ApplicationsPage } from "./pages/ApplicationsPage";
import { RunResultsPage } from "./pages/RunResultsPage";
import { RunsPage } from "./pages/RunsPage";

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">Automated Job Funnel</p>
          <h1>Operator Console</h1>
          <p className="brand-copy">
            Dense internal UI for reviewing scored applications, monitoring runs, and drilling into batch output.
          </p>
        </div>

        <nav className="nav">
          <NavLink className="nav-link" to="/applications">
            Applications
          </NavLink>
          <NavLink className="nav-link" to="/runs">
            Runs
          </NavLink>
        </nav>

        <div className="sidebar-note">
          <p>Views are server-driven and use the FastAPI list endpoints directly.</p>
        </div>
      </aside>

      <main className="workspace">
        <Routes>
          <Route path="/" element={<ApplicationsPage />} />
          <Route path="/applications" element={<ApplicationsPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunResultsPage />} />
        </Routes>
      </main>
    </div>
  );
}
