import { type MouseEvent, useId, useState } from "react";

type SparklinePoint = {
  label: string;
  value: number | null;
};

type NumericSparklineProps = {
  points: SparklinePoint[];
  unit?: string;
};

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

export function NumericSparkline({ points, unit = "" }: NumericSparklineProps) {
  const gradientId = useId().replace(/:/g, "");
  const [hoveredPointIndex, setHoveredPointIndex] = useState<number | null>(null);

  if (points.length < 2) {
    return <p className="status-text">Not enough data for trend chart.</p>;
  }

  const width = 1600;
  const height = 200;
  const topPadding = 18;
  const bottomPadding = 44;
  const leftPadding = 0;
  const rightPadding = 0;
  const chartWidth = width - leftPadding - rightPadding;
  const chartHeight = height - topPadding - bottomPadding;
  const denominator = Math.max(1, points.length - 1);
  const chartPoints = points.map((point, index) => ({
    ...point,
    x: leftPadding + (index / denominator) * chartWidth,
  }));
  const validPoints = chartPoints.filter((point) => typeof point.value === "number") as Array<{
    label: string;
    value: number;
    x: number;
  }>;

  if (validPoints.length < 2) {
    return <p className="status-text">Not enough data for trend chart.</p>;
  }

  let minValue = Number.POSITIVE_INFINITY;
  let maxValue = Number.NEGATIVE_INFINITY;
  validPoints.forEach((point) => {
    minValue = Math.min(minValue, point.value);
    maxValue = Math.max(maxValue, point.value);
  });
  if (minValue === maxValue) {
    minValue -= 1;
    maxValue += 1;
  }

  const span = maxValue - minValue;
  const coordinates = validPoints.map((point) => {
    const y = topPadding + ((maxValue - point.value) / span) * chartHeight;
    return { ...point, y };
  });

  const linePath = coordinates
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  const areaPath = `${linePath} L ${last.x} ${height - bottomPadding} L ${first.x} ${height - bottomPadding} Z`;
  const hoveredPoint =
    hoveredPointIndex == null || hoveredPointIndex < 0 || hoveredPointIndex >= coordinates.length
      ? null
      : coordinates[hoveredPointIndex];
  const tooltipX = hoveredPoint == null ? 0 : clamp(hoveredPoint.x, 92, width - 92);
  const tooltipY = hoveredPoint == null ? 0 : clamp(hoveredPoint.y - 18, 22, height - bottomPadding - 22);

  function onChartHover(event: MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || coordinates.length === 0) {
      return;
    }

    const pointerX = ((event.clientX - rect.left) / rect.width) * width;
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;

    coordinates.forEach((point, index) => {
      const distance = Math.abs(point.x - pointerX);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });

    setHoveredPointIndex((previous) => (previous === nearestIndex ? previous : nearestIndex));
  }

  return (
    <div className="sparkline-wrap">
      <svg
        className="sparkline-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Temperature trend"
        onMouseMove={onChartHover}
        onMouseLeave={() => setHoveredPointIndex(null)}
      >
        <defs>
          <linearGradient id={`sparkline-gradient-${gradientId}`} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(255, 255, 255, 0.48)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 0)" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#sparkline-gradient-${gradientId})`} />
        <path className="sparkline-line" d={linePath} />
        {hoveredPoint ? (
          <>
            <line className="sparkline-hover-guide" x1={hoveredPoint.x} y1={topPadding} x2={hoveredPoint.x} y2={height - bottomPadding} />
            <g transform={`translate(${tooltipX} ${tooltipY})`} className="sparkline-tooltip">
              <rect x="-88" y="-26" width="176" height="24" rx="6" />
              <text x="0" y="-10" textAnchor="middle">
                {hoveredPoint.label} · {hoveredPoint.value.toFixed(1)}
                {unit}
              </text>
            </g>
          </>
        ) : null}
        {coordinates.map((point, index) => (
          <circle
            key={`${point.label}-${index}`}
            cx={point.x}
            cy={point.y}
            r={index === coordinates.length - 1 ? 4 : 2.6}
            className={index === coordinates.length - 1 ? "sparkline-dot current" : "sparkline-dot"}
          />
        ))}
      </svg>

      <div className="sparkline-axis-all">
        {chartPoints.map((point, index) => (
          <span
            key={`${point.label}-${index}`}
            className={index === 0 ? "sparkline-axis-label current" : "sparkline-axis-label"}
            style={{ left: `${(point.x / width) * 100}%` }}
          >
            {point.label}
          </span>
        ))}
      </div>

      <div className="sparkline-extents">
        <span>
          Low {clamp(minValue, -99, 99).toFixed(1)}
          {unit}
        </span>
        <span>
          High {clamp(maxValue, -99, 99).toFixed(1)}
          {unit}
        </span>
      </div>
    </div>
  );
}
