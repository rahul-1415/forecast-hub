import { useEffect, useState } from "react";

import { getAnomalies } from "../api/client";
import type { AnomaliesResponse } from "../types";

type AnomaliesPageProps = {
  location: string;
};

export function AnomaliesPage({ location }: AnomaliesPageProps) {
  const [windowDays, setWindowDays] = useState(7);
  const [data, setData] = useState<AnomaliesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    getAnomalies(location, windowDays)
      .then((response) => {
        if (mounted) {
          setData(response as AnomaliesResponse);
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
  }, [location, windowDays]);

  return (
    <section className="dashboard-page">
      <header className="page-header split">
        <div>
          <h2>Weather Anomaly Detector</h2>
          <p>Rapid shifts and outlier conditions detected from historical baselines.</p>
        </div>
        <label className="date-picker" htmlFor="anomaly-window">
          Window
          <select
            id="anomaly-window"
            value={windowDays}
            onChange={(event) => setWindowDays(Number(event.target.value))}
          >
            <option value={3}>3 days</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
        </label>
      </header>

      {loading ? <p className="status-text">Loading anomalies...</p> : null}
      {error ? <p className="status-text error">Unable to load anomalies: {error}</p> : null}

      {data ? (
        <section className="panel">
          <h3>Detected Events</h3>
          {data.items.length === 0 ? (
            <p className="status-text">No anomalies in this window.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Metric</th>
                    <th>Type</th>
                    <th>Severity</th>
                    <th>Observed</th>
                    <th>Expected</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={`${item.detected_at}-${item.metric}-${item.anomaly_type}`}>
                      <td>{new Date(item.detected_at).toLocaleString()}</td>
                      <td>{item.metric}</td>
                      <td>{item.anomaly_type}</td>
                      <td>
                        <span className={`severity ${item.severity}`}>{item.severity}</span>
                      </td>
                      <td>{item.observed_value?.toFixed(2) ?? "-"}</td>
                      <td>{item.expected_value?.toFixed(2) ?? "-"}</td>
                      <td>{item.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}
    </section>
  );
}
