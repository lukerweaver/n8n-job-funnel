import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getStatistics } from "../api";
import type {
  DailyIngestStatistics,
  ScoreDistributionBucket,
  StatisticsResponse,
} from "../types";
import { formatDateOnly } from "../utils";

const DEFAULT_DAYS = "90";
const DEFAULT_HIGH_SCORE_THRESHOLD = "18";
const DEFAULT_BUCKET_SIZE = "2";

function formatDecimal(value: number | null | undefined, digits = 1) {
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
  return `${formatDecimal(value, 1)}%`;
}

function buildPolyline(points: Array<{ x: number; y: number }>) {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

function DailyIngestChart({ items }: { items: DailyIngestStatistics[] }) {
  const data = [...items].reverse();
  const width = 920;
  const height = 280;
  const padding = { top: 20, right: 24, bottom: 36, left: 48 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(
    1,
    ...data.flatMap((item) => [
      item.ingested_job_postings,
      item.high_job_postings,
      item.rolling_7_day_avg_ingested,
      item.rolling_7_day_avg_high,
    ]),
  );

  const xStep = data.length > 1 ? chartWidth / (data.length - 1) : 0;
  const barWidth = Math.max(8, Math.min(24, chartWidth / Math.max(data.length, 1) - 6));
  const yForValue = (value: number) => padding.top + chartHeight - (value / maxValue) * chartHeight;

  const ingestedLine = buildPolyline(
    data.map((item, index) => ({
      x: padding.left + index * xStep,
      y: yForValue(item.rolling_7_day_avg_ingested),
    })),
  );
  const highLine = buildPolyline(
    data.map((item, index) => ({
      x: padding.left + index * xStep,
      y: yForValue(item.rolling_7_day_avg_high),
    })),
  );

  return (
    <div className="chart-shell">
      <div className="chart-legend">
        <span><i className="legend-swatch legend-bar-ingested" /> Daily ingested</span>
        <span><i className="legend-swatch legend-bar-high" /> Daily high-score</span>
        <span><i className="legend-swatch legend-line-ingested" /> Rolling 7-day ingested</span>
        <span><i className="legend-swatch legend-line-high" /> Rolling 7-day high-score</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="Daily ingest statistics chart">
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
          const ingestedHeight = (item.ingested_job_postings / maxValue) * chartHeight;
          const highHeight = (item.high_job_postings / maxValue) * chartHeight;
          const labelEvery = Math.max(1, Math.ceil(data.length / 8));
          return (
            <g key={item.created_date}>
              <rect
                x={centerX - barWidth}
                y={padding.top + chartHeight - ingestedHeight}
                width={barWidth * 0.9}
                height={ingestedHeight}
                rx={4}
                className="chart-bar-ingested"
              />
              <rect
                x={centerX + 2}
                y={padding.top + chartHeight - highHeight}
                width={barWidth * 0.9}
                height={highHeight}
                rx={4}
                className="chart-bar-high"
              />
              {index % labelEvery === 0 || index === data.length - 1 ? (
                <text x={centerX} y={height - 12} textAnchor="middle" className="chart-axis-label">
                  {new Date(item.created_date).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}
                </text>
              ) : null}
            </g>
          );
        })}

        <polyline points={ingestedLine} fill="none" className="chart-line-ingested" />
        <polyline points={highLine} fill="none" className="chart-line-high" />
      </svg>
    </div>
  );
}

function ScoreDistributionChart({ buckets }: { buckets: ScoreDistributionBucket[] }) {
  const width = 920;
  const height = 260;
  const padding = { top: 20, right: 24, bottom: 44, left: 48 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maxCount = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const barGap = 8;
  const barWidth = Math.max(20, chartWidth / Math.max(buckets.length, 1) - barGap);

  return (
    <div className="chart-shell">
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="Score distribution chart">
        {[0, 0.25, 0.5, 0.75, 1].map((step) => {
          const value = maxCount * step;
          const y = padding.top + chartHeight - (value / maxCount) * chartHeight;
          return (
            <g key={step}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} className="chart-grid-line" />
              <text x={padding.left - 8} y={y + 4} textAnchor="end" className="chart-axis-label">
                {Math.round(value)}
              </text>
            </g>
          );
        })}

        {buckets.map((bucket, index) => {
          const x = padding.left + index * (barWidth + barGap);
          const barHeight = (bucket.count / maxCount) * chartHeight;
          return (
            <g key={`${bucket.bucket_start}-${bucket.bucket_end}`}>
              <rect
                x={x}
                y={padding.top + chartHeight - barHeight}
                width={barWidth}
                height={barHeight}
                rx={6}
                className="score-chart-bar"
              />
              <text x={x + barWidth / 2} y={height - 14} textAnchor="middle" className="chart-axis-label">
                {`${formatDecimal(bucket.bucket_start, 0)}-${formatDecimal(bucket.bucket_end, 0)}`}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function StatisticsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<StatisticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const params = useMemo(() => {
    const next = new URLSearchParams(searchParams);
    if (!next.get("days")) {
      next.set("days", DEFAULT_DAYS);
    }
    if (!next.get("high_score_threshold")) {
      next.set("high_score_threshold", DEFAULT_HIGH_SCORE_THRESHOLD);
    }
    if (!next.get("bucket_size")) {
      next.set("bucket_size", DEFAULT_BUCKET_SIZE);
    }
    return next;
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getStatistics(params)
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
    setSearchParams({
      days: DEFAULT_DAYS,
      high_score_threshold: DEFAULT_HIGH_SCORE_THRESHOLD,
      bucket_size: DEFAULT_BUCKET_SIZE,
    });
  }

  const ingested = data?.ingested_jobs;
  const scoreDistribution = data?.score_distribution;

  return (
    <section className="page-grid">
      <div className="page-header">
        <div>
          <p className="eyebrow">Page 5</p>
          <h2>Statistics</h2>
          <p className="page-subtitle stats-page-subtitle">Daily ingest flow and scored-job distribution from the API.</p>
        </div>
        <div className="stat-chip">{scoreDistribution?.total_scored_jobs ?? 0} scored jobs</div>
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

          <label>
            High Score Threshold
            <input
              type="number"
              min="0"
              step="1"
              value={params.get("high_score_threshold") ?? DEFAULT_HIGH_SCORE_THRESHOLD}
              onChange={(event) => updateParam("high_score_threshold", event.target.value)}
            />
          </label>

          <label>
            Score Bucket Size
            <select value={params.get("bucket_size") ?? DEFAULT_BUCKET_SIZE} onChange={(event) => updateParam("bucket_size", event.target.value)}>
              <option value="1">1 point</option>
              <option value="2">2 points</option>
              <option value="5">5 points</option>
            </select>
          </label>

          <div className="filter-actions">
            <button type="button" className="secondary-button" onClick={resetFilters}>
              Reset
            </button>
          </div>
        </div>
      </div>

      {loading ? <p className="state-message">Loading statistics...</p> : null}
      {error ? <p className="state-message error-message">{error}</p> : null}

      {!loading && !error && data ? (
        <>
          <div className="stats-card-grid">
            <div className="panel stats-card">
              <span className="stats-card-label">Ingested Jobs</span>
              <strong>{ingested?.total_ingested_job_postings ?? 0}</strong>
              <p>{ingested?.total_days ?? 0} daily buckets in view</p>
            </div>
            <div className="panel stats-card">
              <span className="stats-card-label">Average Daily Ingest</span>
              <strong>{formatDecimal(ingested?.average_daily_ingested ?? 0, 1)}</strong>
              <p>Rolling line uses the last 7 days</p>
            </div>
            <div className="panel stats-card">
              <span className="stats-card-label">High-Score Jobs</span>
              <strong>{ingested?.total_high_job_postings ?? 0}</strong>
              <p>Threshold {params.get("high_score_threshold")}</p>
            </div>
            <div className="panel stats-card">
              <span className="stats-card-label">Average Score</span>
              <strong>{formatDecimal(scoreDistribution?.average_score, 1)}</strong>
              <p>
                Range {formatDecimal(scoreDistribution?.minimum_score, 1)} to {formatDecimal(scoreDistribution?.maximum_score, 1)}
              </p>
            </div>
          </div>

          <div className="panel detail-panel">
            <div className="stats-panel-header">
              <div>
                <h3>Ingested Jobs</h3>
                <p className="page-subtitle stats-section-subtitle">Daily ingest counts with high-score counts and 7-day rolling averages.</p>
              </div>
            </div>
            {ingested && ingested.items.length > 0 ? <DailyIngestChart items={ingested.items} /> : <p className="state-message">No ingest statistics available.</p>}
          </div>

          <div className="panel table-panel">
            {ingested && ingested.items.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Ingested</th>
                    <th>7D Avg Ingested</th>
                    <th>High-Score</th>
                    <th>7D Avg High</th>
                    <th>% High</th>
                    <th>7D Avg % High</th>
                  </tr>
                </thead>
                <tbody>
                  {ingested.items.map((item) => (
                    <tr key={item.created_date}>
                      <td>{formatDateOnly(item.created_date)}</td>
                      <td>{item.ingested_job_postings}</td>
                      <td>{formatDecimal(item.rolling_7_day_avg_ingested, 1)}</td>
                      <td>{item.high_job_postings}</td>
                      <td>{formatDecimal(item.rolling_7_day_avg_high, 1)}</td>
                      <td>{formatPercent(item.percentage_high)}</td>
                      <td>{formatPercent(item.rolling_7_day_percentage)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>

          <div className="panel detail-panel">
            <div className="stats-panel-header">
              <div>
                <h3>Score Distribution</h3>
                <p className="page-subtitle stats-section-subtitle">Histogram view of scored applications using the selected bucket size.</p>
              </div>
            </div>
            {scoreDistribution && scoreDistribution.buckets.length > 0 ? (
              <ScoreDistributionChart buckets={scoreDistribution.buckets} />
            ) : (
              <p className="state-message">No scored applications are available yet.</p>
            )}
          </div>

          <div className="panel table-panel">
            {scoreDistribution && scoreDistribution.buckets.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Score Range</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {scoreDistribution.buckets.map((bucket) => (
                    <tr key={`${bucket.bucket_start}-${bucket.bucket_end}`}>
                      <td>{`${formatDecimal(bucket.bucket_start, 0)} - ${formatDecimal(bucket.bucket_end, 0)}`}</td>
                      <td>{bucket.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}
