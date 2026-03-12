import type {
  LocationSuggestion,
  NotificationChannel,
  NotificationConnectStartResponse,
  NotificationConnectStatusResponse,
  NotificationDeliveryLog,
  NotificationSubscription,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  let lastNetworkError: Error | null = null;

  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(url, init);
      if (!response.ok) {
        const errorBody = await response.text();
        throw new Error(`Request failed (${response.status})${errorBody ? `: ${errorBody}` : ""}`);
      }
      return response.json() as Promise<T>;
    } catch (error) {
      if (!(error instanceof TypeError)) {
        throw error;
      }

      lastNetworkError = error;
      if (attempt < 2) {
        const delayMs = 250 * (attempt + 1);
        await new Promise((resolve) => window.setTimeout(resolve, delayMs));
      }
    }
  }

  throw lastNetworkError ?? new Error("Request failed");
}

export async function getOverview(location: string) {
  return request(`/v1/dashboard/overview?location=${encodeURIComponent(location)}`);
}

export async function getLocationSuggestions(query: string, limit = 6): Promise<LocationSuggestion[]> {
  return request(
    `/v1/dashboard/location-suggestions?query=${encodeURIComponent(query)}&limit=${encodeURIComponent(String(limit))}`,
  );
}

export async function getPlan(location: string, targetDate: string) {
  return request(
    `/v1/dashboard/plan?location=${encodeURIComponent(location)}&target_date=${encodeURIComponent(targetDate)}`,
  );
}

export async function getOutfit(location: string, targetDate: string) {
  return request(
    `/v1/dashboard/outfit?location=${encodeURIComponent(location)}&target_date=${encodeURIComponent(targetDate)}`,
  );
}

export async function getHealth(location: string, targetDate: string) {
  return request(
    `/v1/dashboard/health?location=${encodeURIComponent(location)}&target_date=${encodeURIComponent(targetDate)}`,
  );
}

export async function getAnomalies(location: string, windowDays: number) {
  return request(
    `/v1/dashboard/anomalies?location=${encodeURIComponent(location)}&window_days=${windowDays}`,
  );
}

export async function getNotificationSubscriptions() {
  const response = await request<{ items: NotificationSubscription[] }>("/v1/notifications/subscriptions");
  return response.items;
}

export async function upsertNotificationSubscription(payload: {
  location_name: string;
  channel: NotificationChannel;
  destination: string;
  enabled: boolean;
  schedule_time: string;
  timezone: string;
  include_outfit: boolean;
  include_health: boolean;
  include_plan: boolean;
  quiet_hours_enabled: boolean;
  quiet_start: string;
  quiet_end: string;
  escalation_enabled: boolean;
}) {
  return request<NotificationSubscription>("/v1/notifications/subscriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function startNotificationConnect(payload: {
  location_name: string;
  channel: NotificationChannel;
  enabled: boolean;
  schedule_time: string;
  timezone: string;
  include_outfit: boolean;
  include_health: boolean;
  include_plan: boolean;
  quiet_hours_enabled: boolean;
  quiet_start: string;
  quiet_end: string;
  escalation_enabled: boolean;
}) {
  return request<NotificationConnectStartResponse>("/v1/notifications/connect/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getNotificationConnectStatus(token: string) {
  return request<NotificationConnectStatusResponse>(
    `/v1/notifications/connect/status?token=${encodeURIComponent(token)}`,
  );
}

export async function completeTelegramNotificationConnect(token: string) {
  return request<NotificationConnectStatusResponse>("/v1/notifications/connect/telegram/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export async function sendNotificationTest(subscriptionId: number, forceSeverity: "normal" | "high" = "normal") {
  return request<{ status: string; job_id: number; message: string }>("/v1/notifications/send-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subscription_id: subscriptionId, force_severity: forceSeverity }),
  });
}

export async function getNotificationDeliveryLogs(limit = 25) {
  const response = await request<{ items: NotificationDeliveryLog[] }>(
    `/v1/notifications/delivery-logs?limit=${encodeURIComponent(String(limit))}`,
  );
  return response.items;
}
