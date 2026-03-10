import { useEffect, useRef, useState } from "react";

import { getHealth } from "../api/client";
import { CircularGauge } from "../components/CircularGauge";
import type { HealthResponse } from "../types";
import { formatTextTimes, type TimeFormat } from "../utils/time";

type HealthPageProps = {
  location: string;
  timeFormat: TimeFormat;
};

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

function toneForRisk(value: number, invert = false): "good" | "warning" | "danger" {
  const normalized = Math.max(0, Math.min(100, value));
  if (invert) {
    if (normalized >= 70) {
      return "good";
    }
    if (normalized >= 40) {
      return "warning";
    }
    return "danger";
  }
  if (normalized >= 70) {
    return "danger";
  }
  if (normalized >= 40) {
    return "warning";
  }
  return "good";
}

export function HealthPage({ location, timeFormat }: HealthPageProps) {
  const [targetDate, setTargetDate] = useState(todayIsoDate());
  const [data, setData] = useState<HealthResponse | null>(null);
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
        <div className="date-picker date-picker-inline">
          <button type="button" className="date-picker-label-button" onClick={openDatePicker}>
            Date
          </button>
          <input
            ref={dateInputRef}
            id="health-date"
            type="date"
            value={targetDate}
            onChange={(event) => setTargetDate(event.target.value)}
          />
        </div>
      </header>

      {loading ? <p className="status-text">Loading health risks...</p> : null}
      {error ? <p className="status-text error">Unable to load health risks: {error}</p> : null}

      {data ? (
        <>
          <section className="panel">
            <h3>Risk Scores</h3>
            <div className="risk-ring-grid">
              <CircularGauge
                label="Heat Risk"
                value={data.heat_risk}
                max={100}
                unit="%"
                tone={toneForRisk(data.heat_risk)}
              />
              <CircularGauge
                label="Cold Risk"
                value={data.cold_risk}
                max={100}
                unit="%"
                tone={toneForRisk(data.cold_risk)}
              />
              <CircularGauge
                label="Dehydration Risk"
                value={data.dehydration_risk}
                max={100}
                unit="%"
                tone={toneForRisk(data.dehydration_risk)}
              />
              <CircularGauge
                label="Asthma Proxy Risk"
                value={data.asthma_proxy_risk}
                max={100}
                unit="%"
                tone={toneForRisk(data.asthma_proxy_risk)}
              />
              <CircularGauge
                label="Sleep Comfort"
                value={data.sleep_comfort_index}
                max={100}
                unit="%"
                tone={toneForRisk(data.sleep_comfort_index, true)}
              />
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
