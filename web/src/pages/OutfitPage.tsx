import { useEffect, useRef, useState } from "react";

import { getOutfit } from "../api/client";
import { MetricCard } from "../components/MetricCard";
import type { OutfitResponse } from "../types";
import { formatTextTimes, type TimeFormat } from "../utils/time";

type OutfitPageProps = {
  location: string;
  timeFormat: TimeFormat;
};

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

export function OutfitPage({ location, timeFormat }: OutfitPageProps) {
  const [targetDate, setTargetDate] = useState(todayIsoDate());
  const [data, setData] = useState<OutfitResponse | null>(null);
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

    getOutfit(location, targetDate)
      .then((response) => {
        if (mounted) {
          setData(response as OutfitResponse);
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
          <h2>Outfit + Packing Assistant</h2>
        </div>
        <div className="date-picker date-picker-inline">
          <button type="button" className="date-picker-label-button" onClick={openDatePicker}>
            Date
          </button>
          <input
            ref={dateInputRef}
            id="outfit-date"
            type="date"
            value={targetDate}
            onChange={(event) => setTargetDate(event.target.value)}
          />
        </div>
      </header>

      {loading ? <p className="status-text">Loading outfit guidance...</p> : null}
      {error ? <p className="status-text error">Unable to load outfit guidance: {error}</p> : null}

      {data ? (
        <>
          <div className="metric-grid">
            <MetricCard label="Layer Level" value={data.layer_level.toUpperCase()} />
            <MetricCard label="Umbrella" value={data.umbrella ? "Yes" : "No"} tone={data.umbrella ? "warning" : "good"} />
            <MetricCard label="Shoes" value={data.shoes} />
            <MetricCard label="Sunscreen" value={data.sunscreen} />
            <MetricCard label="Hydration" value={`${data.hydration_liters.toFixed(1)} L`} tone="good" />
          </div>

          <section className="panel">
            <h3>AI Summary</h3>
            <p className="long-summary">{formatTextTimes(data.summary, timeFormat)}</p>
          </section>
        </>
      ) : null}
    </section>
  );
}
