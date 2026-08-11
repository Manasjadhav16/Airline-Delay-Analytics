import { API_BASE_URL } from "./config";

async function handleResponse(response) {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // response wasn't JSON, fall back to statusText
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function fetchMetadata() {
  const response = await fetch(`${API_BASE_URL}/metadata`);
  return handleResponse(response);
}

export async function fetchStats(category) {
  const response = await fetch(`${API_BASE_URL}/stats/${category}`);
  return handleResponse(response);
}

export async function predictDelay(payload) {
  const response = await fetch(`${API_BASE_URL}/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse(response);
}
