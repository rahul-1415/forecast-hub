import type { ReactNode } from "react";

type MetricCardProps = {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "warning" | "danger";
  hint?: ReactNode;
  deltaValue?: number | null;
  deltaUnit?: string;
  deltaLabel?: string;
};

function formatDeltaValue(value: number) {
  const absolute = Math.abs(value);
  if (absolute >= 10) {
    return absolute.toFixed(0);
  }
  return absolute.toFixed(1);
}

export function MetricCard({
  label,
  value,
  tone = "neutral",
  hint,
  deltaValue = null,
  deltaUnit = "",
  deltaLabel,
}: MetricCardProps) {
  const hasDelta = typeof deltaValue === "number" && Number.isFinite(deltaValue);
  const trendDirection = !hasDelta
    ? null
    : deltaValue > 0
      ? "up"
      : deltaValue < 0
        ? "down"
        : "flat";
  const trendGlyph = trendDirection === "up" ? "↑" : trendDirection === "down" ? "↓" : "→";

  return (
    <article className={`metric-card ${tone}`}>
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      {hasDelta ? (
        <p className={`metric-delta ${trendDirection}`}>
          {trendGlyph} {formatDeltaValue(deltaValue)}
          {deltaUnit}
          {deltaLabel ? ` ${deltaLabel}` : ""}
        </p>
      ) : null}
      {hint ? <div className="metric-hint">{hint}</div> : null}
    </article>
  );
}
