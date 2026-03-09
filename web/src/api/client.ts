import type { LocationSuggestion } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  let lastNetworkError: Error | null = null;

  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
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
