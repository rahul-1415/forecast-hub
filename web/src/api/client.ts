const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function getOverview(location: string) {
  return request(`/v1/dashboard/overview?location=${encodeURIComponent(location)}`);
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
