import { CircularGauge } from "../components/CircularGauge";
import { MetricCard } from "../components/MetricCard";
import { RangeBar } from "../components/RangeBar";
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
  const currentTemperature = data?.current_temperature_c ?? null;
  const suggestionsTitle = predictionSource === "custom_ml" ? "AI Suggestions (Custom ML)" : "AI Suggestions";
  const nextHourReference =
    predictionSource === "custom_ml"
      ? (data?.next_hour_temperature_custom_model_c ?? data?.next_hour_temperature_prediction_c ?? null)
      : (data?.next_hour_temperature_open_meteo_c ?? data?.next_hour_temperature_prediction_c ?? null);
  const nextHourDelta =
    nextHourReference != null && currentTemperature != null ? nextHourReference - currentTemperature : null;

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
            <MetricCard
              label="Min Temp (24h)"
              value={`${data.next_24h.min_temp_c?.toFixed(1) ?? "-"} C`}
              deltaValue={
                data.next_24h.min_temp_c != null && currentTemperature != null
                  ? data.next_24h.min_temp_c - currentTemperature
                  : null
              }
              deltaUnit="°"
              deltaLabel="vs now"
            />
            <MetricCard
              label="Max Temp (24h)"
              value={`${data.next_24h.max_temp_c?.toFixed(1) ?? "-"} C`}
              deltaValue={
                data.next_24h.max_temp_c != null && currentTemperature != null
                  ? data.next_24h.max_temp_c - currentTemperature
                  : null
              }
              deltaUnit="°"
              deltaLabel="vs now"
            />
            <MetricCard
              label="Total Precipitation"
              value={`${data.next_24h.precipitation_total_mm?.toFixed(1) ?? "-"} mm`}
              deltaValue={
                data.next_24h.precipitation_total_mm != null ? data.next_24h.precipitation_total_mm - 5 : null
              }
              deltaUnit="mm"
              deltaLabel="vs moderate"
            />
            <MetricCard
              label="Avg Wind"
              value={`${data.next_24h.avg_wind_kph?.toFixed(1) ?? "-"} kph`}
              deltaValue={data.next_24h.avg_wind_kph != null ? data.next_24h.avg_wind_kph - 20 : null}
              deltaUnit="kph"
              deltaLabel="vs breezy"
            />
            <MetricCard
              label="Alert Level"
              value={data.alert_level.toUpperCase()}
              tone={data.alert_level === "high" ? "danger" : data.alert_level === "medium" ? "warning" : "good"}
            />
            <MetricCard
              label="Anomalies (7d)"
              value={`${data.anomalies_last_7d}`}
              tone="warning"
              deltaValue={nextHourDelta}
              deltaUnit="°"
              deltaLabel="next hour"
            />
          </div>

          <section className="panel">
            <h3>Visual Snapshot</h3>
            <div className="overview-visual-grid">
              <article className="visual-card">
                <p className="visual-card-title">Temperature Band (24h)</p>
                <RangeBar
                  min={data.next_24h.min_temp_c ?? null}
                  max={data.next_24h.max_temp_c ?? null}
                  marker={data.current_temperature_c ?? null}
                  unit="°C"
                />
              </article>
              <CircularGauge
                label="Precipitation Load"
                value={data.next_24h.precipitation_total_mm ?? null}
                max={25}
                unit=" mm"
                caption="Next 24h"
                tone="warning"
              />
              <CircularGauge
                label="Wind Intensity"
                value={data.next_24h.avg_wind_kph ?? null}
                max={45}
                unit=" kph"
                caption="Average next 24h"
                tone="neutral"
              />
              <CircularGauge
                label="Anomaly Pressure"
                value={Math.min(100, data.anomalies_last_7d * 12.5)}
                max={100}
                unit="%"
                caption="Last 7 days"
                tone={data.alert_level === "high" ? "danger" : data.alert_level === "medium" ? "warning" : "good"}
              />
            </div>
          </section>

          <section className="panel">
            <h3>{suggestionsTitle}</h3>
            {predictionSource === "custom_ml" ? (
              <p className="panel-source-note">
                AI-generated suggestions are based solely on Custom ML model outputs, not Open-Meteo.
              </p>
            ) : null}
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
