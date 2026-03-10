type RangeBarProps = {
  min: number | null;
  max: number | null;
  marker?: number | null;
  unit?: string;
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function formatNumber(value: number, unit: string) {
  return `${value.toFixed(1)}${unit}`;
}

export function RangeBar({ min, max, marker = null, unit = "" }: RangeBarProps) {
  if (min == null || max == null) {
    return <p className="status-text">Range unavailable</p>;
  }

  const lower = Math.min(min, max);
  const upper = Math.max(min, max);
  const markerValue = marker ?? lower;
  const paddedLower = lower - 2;
  const paddedUpper = upper + 2;
  const span = Math.max(0.0001, paddedUpper - paddedLower);

  const start = clamp(((lower - paddedLower) / span) * 100, 0, 100);
  const end = clamp(((upper - paddedLower) / span) * 100, 0, 100);
  const markerPosition = clamp(((markerValue - paddedLower) / span) * 100, 0, 100);

  return (
    <div className="range-bar-wrap">
      <div className="range-track" aria-hidden="true">
        <span className="range-segment" style={{ left: `${start}%`, width: `${Math.max(2, end - start)}%` }} />
        <span className="range-marker" style={{ left: `${markerPosition}%` }} />
      </div>
      <div className="range-legend">
        <span>{formatNumber(lower, unit)}</span>
        <span>{formatNumber(markerValue, unit)}</span>
        <span>{formatNumber(upper, unit)}</span>
      </div>
    </div>
  );
}
