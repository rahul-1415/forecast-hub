import type { ReactNode } from "react";

type MetricCardProps = {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "warning" | "danger";
  hint?: ReactNode;
};

export function MetricCard({ label, value, tone = "neutral", hint }: MetricCardProps) {
  return (
    <article className={`metric-card ${tone}`}>
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      {hint ? <p className="metric-hint">{hint}</p> : null}
    </article>
  );
}
