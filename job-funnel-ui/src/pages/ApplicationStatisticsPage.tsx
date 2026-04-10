import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getApplicationStatistics } from "../api";
import type { ApplicationStatisticsResponse, DailyApplicationActivity } from "../types";

const DEFAULT_DAYS = "90";

function formatDecimal(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function formatPercent(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return "N/A";
  }
  return `${formatDecimal(value, 2)}%`;
}

function buildPolyline(points: Array<{ x: number; y: number }>) {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

function totalActivity(items: DailyApplicationActivity[], key: "screenings" | "interviews" | "rejections" | "offers") {
  return items.reduce((total, item) => total + item[key], 0);
}

function ApplicationActivityChart({ items }: { items: DailyApplicationActivity[] }) {
  const data = [...items].reverse();
  const width = 920;
  const height = 280;
  const padding = { top: 20, right: 24, bottom: 36, left: 48 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(
    1,
    ...data.flatMap((item) => [
      item.applications,
      item.screenings,
      item.interviews,
      item.rejections,
      item.offers,
      item.rolling_28_day_avg_applications,
      item.rolling_28_day_avg_screenings,
      item.rolling_28_day_avg_interviews,
      item.rolling_28_day_avg_rejections,
      item.rolling_28_day_avg_offers,
    ]),
  );
  const xStep = data.length > 1 ? chartWidth / (data.length - 1) : 0;
  const yForValue = (value: number) => padding.top + chartHeight - (value / maxValue) * chartHeight;
  const lineFor = (
    key:
      | "rolling_28_day_avg_applications"
      | "rolling_28_day_avg_screenings"
      | "rolling_28_day_avg_interviews"
      | "rolling_28_day_avg_rejections"
      | "rolling_28_day_avg_offers",
  ) =>
    buildPolyline(
      data.map((item, index) => ({
        x: padding.left + index * xStep,
        y: yForValue(item[key]),
      })),
    );

  return (
    <div className="chart-shell">
      <div className="chart-legend">
        <span><i className="legend-swatch legend-line-applications" /> 28D avg applied</span>
        <span><i className="legend-swatch legend-line-screenings" /> 28D avg screenings</span>
        <span><i className="legend-swatch legend-line-interviews" /> 28D avg interviews</span>
        <span><i className="legend-swatch legend-line-rejections" /> 28D avg rejections</span>
        <span><i className="legend-swatch legend-line-offers" /> 28D avg offers</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="Daily application activity chart">
        {[0, 0.25, 0.5, 0.75, 1].map((step) => {
          const value = maxValue * step;
          const y = yForValue(value);
          return (
            <g key={step}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} className="chart-grid-line" />
              <text x={padding.left - 8} y={y + 4} textAnchor="end" className="chart-axis-label">
                {Math.round(value)}
              </text>
            </g>
          );
        })}

        {data.map((item, index) => {
          const centerX = padding.left + index * xStep;
          const labelEvery = Math.max(1, Math.ceil(data.length / 8));
          return index % labelEvery === 0 || index === data.length - 1 ? (
            <text key={item.activity_date} x={centerX} y={height - 12} textAnchor="middle" className="chart-axis-label">
              {new Date(item.activity_date).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}
            </text>
          ) : null;
        })}

        <polyline points={lineFor("rolling_28_day_avg_applications")} fill="none" className="chart-line-applications" />
        <polyline points={lineFor("rolling_28_day_avg_screenings")} fill="none" className="chart-line-screenings" />
        <polyline points={lineFor("rolling_28_day_avg_interviews")} fill="none" className="chart-line-interviews" />
        <polyline points={lineFor("rolling_28_day_avg_rejections")} fill="none" className="chart-line-rejections" />
        <polyline points={lineFor("rolling_28_day_avg_offers")} fill="none" className="chart-line-offers" />
      </svg>
    </div>
  );
}

export function ApplicationStatisticsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<ApplicationStatisticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("days")) {
      next.set("days", DEFAULT_DAYS);
    }
    return next;
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getApplicationStatistics(params)
      .then((response) => {
        if (!cancelled) {
          setData(response);
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
    setSearchParams(next);
  }

  function resetFilters() {
    setSearchParams({ days: DEFAULT_DAYS });
  }

  const dailyActivity = data?.daily_activity ?? [];

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 6</p>
          <h2>Job Application Statistics</h2>
          <p className="page-subtitle stats-page-subtitle">Application lifecycle funnel, outcomes, duration metrics, and daily activity.</p>
        </div>
        <div className="stat-chip">{data?.total_applications ?? 0} applications</div>
      </div>

      <div className="panel filter-panel">
        <div className="filter-grid stats-filter-grid">
          <label>
            Lookback
            <select value={params.get("days") ?? DEFAULT_DAYS} onChange={(event) => updateParam("days", event.target.value)}>
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="180">180 days</option>
              <option value="365">365 days</option>
            </select>
          </label>

          <div className="filter-actions">
            <button type="button" className="secondary-button" onClick={resetFilters}>
              Reset
            </button>
          </div>
        </div>
      </div>

      {loading ? <p className="state-message">Loading application statistics...</p> : null}
      {error ? <p className="state-message error-message">{error}</p> : null}

      {!loading && !error && data ? (
        <>
          <div className="stats-card-grid">
            <div className="panel stats-card">
              <span className="stats-card-label">Applications</span>
              <strong>{data.total_applications}</strong>
              <p>Rows in the selected lookback</p>
            </div>
            <div className="panel stats-card">
              <span className="stats-card-label">Screenings</span>
              <strong>{totalActivity(dailyActivity, "screenings")}</strong>
              <p>Screening dates in view</p>
            </div>
            <div className="panel stats-card">
              <span className="stats-card-label">Interviews</span>
              <strong>{totalActivity(dailyActivity, "interviews")}</strong>
              <p>Interview rounds in view</p>
            </div>
            <div className="panel stats-card">
              <span className="stats-card-label">Offers</span>
              <strong>{totalActivity(dailyActivity, "offers")}</strong>
              <p>Offer dates in view</p>
            </div>
          </div>

          <div className="panel table-panel">
            <div className="stats-panel-header">
              <div>
                <h3>Funnel</h3>
                <p className="page-subtitle stats-section-subtitle">Counts plus conversion from the prior stage and from submitted applications.</p>
              </div>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Count</th>
                  <th>% from Start</th>
                  <th>% from Previous</th>
                </tr>
              </thead>
              <tbody>
                {data.funnel.map((stage) => (
                  <tr key={stage.label}>
                    <td>{stage.label}</td>
                    <td>{stage.count}</td>
                    <td>{formatPercent(stage.percentage_from_start)}</td>
                    <td>{formatPercent(stage.percentage_from_previous)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="split-layout">
            <div className="panel table-panel">
              <div className="stats-panel-header">
                <div>
                  <h3>Status Counts</h3>
                  <p className="page-subtitle stats-section-subtitle">Notified rows are folded into Submitted.</p>
                </div>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Count</th>
                    <th>Share</th>
                  </tr>
                </thead>
                <tbody>
                  {data.status_counts.map((status) => (
                    <tr key={status.label}>
                      <td>{status.label}</td>
                      <td>{status.count}</td>
                      <td>{formatPercent(status.percentage)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="panel table-panel">
              <div className="stats-panel-header">
                <div>
                  <h3>Stage Reached</h3>
                  <p className="page-subtitle stats-section-subtitle">Derived from screening dates and the highest interview round.</p>
                </div>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Count</th>
                    <th>Share</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stage_counts.map((stage) => (
                    <tr key={stage.label}>
                      <td>{stage.label}</td>
                      <td>{stage.count}</td>
                      <td>{formatPercent(stage.percentage)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel table-panel">
            <div className="stats-panel-header">
              <div>
                <h3>Cycle Time</h3>
                <p className="page-subtitle stats-section-subtitle">Durations are in days and rounded to two decimal places.</p>
              </div>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Count</th>
                  <th>Average Days</th>
                  <th>Min Days</th>
                  <th>Max Days</th>
                </tr>
              </thead>
              <tbody>
                {data.duration_metrics.map((metric) => (
                  <tr key={metric.label}>
                    <td>{metric.label}</td>
                    <td>{metric.count}</td>
                    <td>{formatDecimal(metric.average_days)}</td>
                    <td>{formatDecimal(metric.minimum_days)}</td>
                    <td>{formatDecimal(metric.maximum_days)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel detail-panel">
            <div className="stats-panel-header">
              <div>
                <h3>Daily Activity</h3>
                <p className="page-subtitle stats-section-subtitle">Rolling 28-day averages for applied applications, screenings, interview rounds, rejections, and offers.</p>
              </div>
            </div>
            {dailyActivity.length > 0 ? <ApplicationActivityChart items={dailyActivity} /> : <p className="state-message">No application activity available.</p>}
          </div>
        </>
      ) : null}
    </section>
  );
}
