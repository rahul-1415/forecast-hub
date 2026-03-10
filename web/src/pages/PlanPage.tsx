import { useEffect, useRef, useState } from "react";

import { getPlan } from "../api/client";
import type { PlanResponse } from "../types";
import { formatHourLabel, formatTextTimes, type TimeFormat } from "../utils/time";

type PlanPageProps = {
  location: string;
  timeFormat: TimeFormat;
};

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

export function PlanPage({ location, timeFormat }: PlanPageProps) {
  const [targetDate, setTargetDate] = useState(todayIsoDate());
  const [data, setData] = useState<PlanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const dateInputRef = useRef<HTMLInputElement | null>(null);

  function openDatePicker() {
    const input = dateInputRef.current;
    if (!input) {
      return;
    }

    const pickerInput = input as HTMLInputElement & { showPicker?: () => void };
    if (typeof pickerInput.showPicker === "function") {
      pickerInput.showPicker();
      return;
    }

    input.focus();
    input.click();
  }

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

  return (
    <section className="dashboard-page">
      <header className="page-header split">
        <div>
          <h2>Daily Plan Copilot</h2>
        </div>
        <div className="date-picker date-picker-inline">
          <button type="button" className="date-picker-label-button" onClick={openDatePicker}>
            Date
          </button>
          <input
            ref={dateInputRef}
            id="plan-date"
            type="date"
            value={targetDate}
            onChange={(event) => setTargetDate(event.target.value)}
          />
        </div>
      </header>

      {loading ? <p className="status-text">Loading plan...</p> : null}
      {error ? <p className="status-text error">Unable to load plan: {error}</p> : null}

      {data ? (
        <>
          <section className="panel">
            <h3>Recommended Windows</h3>
            <div className="window-grid">
              {data.windows.map((window) => (
                <article key={window.category} className="window-card">
                  <p className="window-title">{window.category}</p>
                  <p className="window-meta">
                    {formatHourLabel(window.best_hour, timeFormat)} · {window.score.toFixed(0)}/100
                  </p>
                  <p className="window-summary">{formatTextTimes(window.summary, timeFormat)}</p>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </section>
  );
}
