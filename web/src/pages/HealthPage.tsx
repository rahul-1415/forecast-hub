import { useEffect, useState } from "react";

import { getHealth } from "../api/client";
import type { HealthResponse } from "../types";
import { formatTextTimes, type TimeFormat } from "../utils/time";

type HealthPageProps = {
  location: string;
  timeFormat: TimeFormat;
};

type RiskBarProps = {
  label: string;
  value: number;
  invert?: boolean;
};

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

function RiskBar({ label, value, invert = false }: RiskBarProps) {
  const normalized = Math.max(0, Math.min(100, value));
  const tone = invert ? (normalized >= 70 ? "good" : normalized >= 40 ? "warning" : "danger") : normalized >= 70 ? "danger" : normalized >= 40 ? "warning" : "good";

  return (
    <div className="risk-row">
      <div className="risk-label-wrap">
        <p>{label}</p>
        <strong>{normalized}</strong>
      </div>
      <div className="risk-track">
        <div className={`risk-fill ${tone}`} style={{ width: `${normalized}%` }} />
      </div>
    </div>
  );
}

export function HealthPage({ location, timeFormat }: HealthPageProps) {
  const [targetDate, setTargetDate] = useState(todayIsoDate());
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    getHealth(location, targetDate)
      .then((response) => {
        if (mounted) {
          setData(response as HealthResponse);
        }
      })
      .catch((err: Error) => {
        if (mounted) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (mounted) {
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [location, targetDate]);

  return (
    <section className="dashboard-page">
      <header className="page-header split">
        <div>
          <h2>Health Alerts Generator</h2>
        </div>
        <label className="date-picker" htmlFor="health-date">
          Date
          <input
            id="health-date"
            type="date"
            value={targetDate}
            onChange={(event) => setTargetDate(event.target.value)}
          />
        </label>
      </header>

      {loading ? <p className="status-text">Loading health risks...</p> : null}
      {error ? <p className="status-text error">Unable to load health risks: {error}</p> : null}

      {data ? (
        <>
          <section className="panel">
            <h3>Risk Scores</h3>
            <div className="risk-grid">
              <RiskBar label="Heat Risk" value={data.heat_risk} />
              <RiskBar label="Cold Risk" value={data.cold_risk} />
              <RiskBar label="Dehydration Risk" value={data.dehydration_risk} />
              <RiskBar label="Asthma Proxy Risk" value={data.asthma_proxy_risk} />
              <RiskBar label="Sleep Comfort Index" value={data.sleep_comfort_index} invert />
            </div>
          </section>

          <section className="panel">
            <h3>AI Summary</h3>
            <p className="long-summary">{formatTextTimes(data.summary, timeFormat)}</p>
          </section>
        </>
      ) : null}
    </section>
  );
}
