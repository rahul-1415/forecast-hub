export type TimeFormat = "12h" | "24h";

export function formatHourLabel(hour: number, timeFormat: TimeFormat): string {
  const normalizedHour = ((Math.trunc(hour) % 24) + 24) % 24;

  if (timeFormat === "24h") {
    return `${String(normalizedHour).padStart(2, "0")}:00`;
  }

  const period = normalizedHour >= 12 ? "PM" : "AM";
  const hour12 = normalizedHour % 12 === 0 ? 12 : normalizedHour % 12;
  return `${hour12}:00 ${period}`;
}

export function formatDateTimeLabel(value: string, timeFormat: TimeFormat): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString(undefined, {
    hour12: timeFormat === "12h",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatHourFromTimestamp(value: string, timeFormat: TimeFormat): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }

  return date.toLocaleTimeString(undefined, {
    hour12: timeFormat === "12h",
    hour: "numeric",
  });
}

export function formatTextTimes(value: string, timeFormat: TimeFormat): string {
  if (timeFormat === "24h" || !value) {
    return value;
  }

  return value.replace(/\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[AaPp]\.?[Mm]\.?)/g, (_, hourText, minuteText) => {
    const hour24 = Number.parseInt(hourText, 10);
    const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
    const period = hour24 >= 12 ? "PM" : "AM";
    return `${hour12}:${minuteText} ${period}`;
  });
}
