import { MetricCard } from "../components/MetricCard";
import type { OverviewResponse } from "../types";
import { formatTextTimes, type TimeFormat } from "../utils/time";

type OverviewPageProps = {
  data: OverviewResponse | null;
  loading: boolean;
  error: string | null;
  predictionSource: "open_meteo" | "custom_ml";
  timeFormat: TimeFormat;
};

export function OverviewPage({ data, loading, error, predictionSource, timeFormat }: OverviewPageProps) {
  return (
    <section className="dashboard-page">
      <header className="page-header">
        <h2>Overview</h2>
      </header>

      {loading ? (
        <section className="panel loading-panel">
          <span className="loader-ring" aria-hidden="true" />
          <p className="status-text">Loading overview...</p>
        </section>
      ) : null}

      {error ? (
        <section className="panel">
          <p className="status-text error">Unable to load overview: {error}</p>
        </section>
      ) : null}

      {!loading && !error && !data ? (
        <section className="panel">
          <p className="status-text">No overview data available.</p>
        </section>
      ) : null}

      {!loading && !error && data ? (
        <>
          <div className="metric-grid">
            <MetricCard label="Min Temp (24h)" value={`${data.next_24h.min_temp_c?.toFixed(1) ?? "-"} C`} />
            <MetricCard label="Max Temp (24h)" value={`${data.next_24h.max_temp_c?.toFixed(1) ?? "-"} C`} />
            <MetricCard
              label="Total Precipitation"
              value={`${data.next_24h.precipitation_total_mm?.toFixed(1) ?? "-"} mm`}
            />
            <MetricCard label="Avg Wind" value={`${data.next_24h.avg_wind_kph?.toFixed(1) ?? "-"} kph`} />
            <MetricCard
              label="Alert Level"
              value={data.alert_level.toUpperCase()}
              tone={data.alert_level === "high" ? "danger" : data.alert_level === "medium" ? "warning" : "good"}
            />
            <MetricCard label="Anomalies (7d)" value={`${data.anomalies_last_7d}`} tone="warning" />
          </div>

          <section className="panel">
            <h3>AI Suggestions</h3>
            <ul className="advice-list">
              {data.top_recommendations.map((tip, index) => (
                <li key={`${index}-${tip}`}>{formatTextTimes(tip, timeFormat)}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </section>
  );
}
