import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { getPlan } from "../api/client";
import type { PlanResponse } from "../types";

type PlanPageProps = {
  location: string;
};

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

export function PlanPage({ location }: PlanPageProps) {
  const [targetDate, setTargetDate] = useState(todayIsoDate());
  const [data, setData] = useState<PlanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    getPlan(location, targetDate)
      .then((response) => {
        if (mounted) {
          setData(response as PlanResponse);
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

  const chartData = useMemo(
    () =>
      (data?.windows ?? []).map((window) => ({
        category: window.category,
        score: window.score,
      })),
    [data],
  );

  return (
    <section className="dashboard-page">
      <header className="page-header split">
        <div>
          <h2>Daily Plan Copilot</h2>
          <p>Best time windows for commute, exercise, and errands.</p>
        </div>
        <label className="date-picker" htmlFor="plan-date">
          Date
          <input id="plan-date" type="date" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} />
        </label>
      </header>

      {loading ? <p className="status-text">Loading plan...</p> : null}
      {error ? <p className="status-text error">Unable to load plan: {error}</p> : null}

      {data ? (
        <>
          <section className="panel chart-panel">
            <h3>Window Scores</h3>
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="4 4" />
                  <XAxis dataKey="category" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Bar dataKey="score" fill="#2a8f6f" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="panel">
            <h3>Recommended Windows</h3>
            <div className="window-grid">
              {data.windows.map((window) => (
                <article key={window.category} className="window-card">
                  <p className="window-title">{window.category}</p>
                  <p className="window-hour">{String(window.best_hour).padStart(2, "0")}:00</p>
                  <p className="window-score">{window.score.toFixed(0)}/100</p>
                  <p className="window-summary">{window.summary}</p>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}
