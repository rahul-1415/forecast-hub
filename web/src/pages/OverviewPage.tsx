import { useEffect, useState } from "react";

import { getOverview } from "../api/client";
import { MetricCard } from "../components/MetricCard";
import type { OverviewResponse } from "../types";

type OverviewPageProps = {
  location: string;
};

export function OverviewPage({ location }: OverviewPageProps) {
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    getOverview(location)
      .then((response) => {
        if (!mounted) {
          return;
        }
        setData(response as OverviewResponse);
      })
      .catch((err: Error) => {
        if (!mounted) {
          return;
        }
        setError(err.message);
      })
      .finally(() => {
        if (mounted) {
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [location]);

  if (loading) {
    return <p className="status-text">Loading overview...</p>;
  }

  if (error) {
    return <p className="status-text error">Unable to load overview: {error}</p>;
  }

  if (!data) {
    return <p className="status-text">No overview data available.</p>;
  }

  const alertTone = data.alert_level === "high" ? "danger" : data.alert_level === "medium" ? "warning" : "good";

  return (
    <section className="dashboard-page">
      <header className="page-header">
        <h2>Overview</h2>
        <p>Generated at {new Date(data.generated_at).toLocaleString()}</p>
      </header>

      <div className="metric-grid">
        <MetricCard label="Min Temp (24h)" value={`${data.next_24h.min_temp_c?.toFixed(1) ?? "-"} C`} />
        <MetricCard label="Max Temp (24h)" value={`${data.next_24h.max_temp_c?.toFixed(1) ?? "-"} C`} />
        <MetricCard
          label="Total Precipitation"
          value={`${data.next_24h.precipitation_total_mm?.toFixed(1) ?? "-"} mm`}
        />
        <MetricCard label="Avg Wind" value={`${data.next_24h.avg_wind_kph?.toFixed(1) ?? "-"} kph`} />
        <MetricCard
          label="Model Next-Hour Temp"
          value={`${data.next_hour_temperature_prediction_c?.toFixed(1) ?? "-"} C`}
          hint="MLflow active model"
        />
        <MetricCard label="Alert Level" value={data.alert_level.toUpperCase()} tone={alertTone} />
        <MetricCard label="Anomalies (7d)" value={`${data.anomalies_last_7d}`} tone="warning" />
      </div>

      <section className="panel">
        <h3>AI Suggestions</h3>
        <ul className="advice-list">
          {data.top_recommendations.map((tip) => (
            <li key={tip}>{tip}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}
