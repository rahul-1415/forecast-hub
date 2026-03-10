type GaugeTone = "neutral" | "good" | "warning" | "danger";

type CircularGaugeProps = {
  label: string;
  value: number | null;
  max: number;
  unit?: string;
  caption?: string;
  tone?: GaugeTone;
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function formatGaugeValue(value: number, unit: string) {
  const rounded = value >= 100 ? value.toFixed(0) : value.toFixed(1);
  return `${rounded}${unit}`;
}

export function CircularGauge({
  label,
  value,
  max,
  unit = "",
  caption,
  tone = "neutral",
}: CircularGaugeProps) {
  const safeMax = Math.max(0.0001, max);
  const numericValue = value == null ? 0 : value;
  const normalized = clamp((numericValue / safeMax) * 100, 0, 100);
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const dash = (normalized / 100) * circumference;

  return (
    <article className={`ring-gauge ${tone}`}>
      <div className="ring-gauge-visual" aria-hidden="true">
        <svg viewBox="0 0 120 120">
          <circle className="ring-track-circle" cx="60" cy="60" r={radius} />
          <circle
            className="ring-progress-circle"
            cx="60"
            cy="60"
            r={radius}
            strokeDasharray={`${dash} ${circumference - dash}`}
          />
        </svg>
        <div className="ring-gauge-center">
          <strong>{value == null ? "--" : formatGaugeValue(value, unit)}</strong>
        </div>
      </div>
      <p className="ring-gauge-label">{label}</p>
      {caption ? <p className="ring-gauge-caption">{caption}</p> : null}
    </article>
  );
}
