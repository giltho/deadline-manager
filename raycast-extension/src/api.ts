import { getAccessToken } from "@raycast/utils";
import { getPreferenceValues } from "@raycast/api";

interface Preferences {
  apiBaseUrl: string;
  discordClientId: string;
}

function getApiBaseUrl(): string {
  let url = getPreferenceValues<Preferences>().apiBaseUrl.trim().replace(/\/$/, "");
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    url = "https://" + url;
  }
  return url;
}

// ── Types (mirroring api/schemas.py) ─────────────────────────────────────────

export interface DeadlineResponse {
  id: number;
  title: string;
  description: string | null;
  due_date: string; // ISO 8601 datetime string
  // Discord snowflake IDs serialized as strings to avoid JS integer precision loss.
  created_by: string;
  created_at: string; // ISO 8601 datetime string
  member_ids: string[];
}

export interface DeadlineCreateRequest {
  title: string;
  due_date: string; // flexible date string, e.g. "2026-06-15" or "15 Jun 2026 17:00"
  description?: string;
  // Discord snowflake IDs as strings to avoid JS integer precision loss.
  member_ids?: string[];
}

export interface GuildMember {
  id: string;
  username: string;
  global_name: string | null;
  nick: string | null;
  avatar: string | null;
}

export interface DeadlineEditRequest {
  new_title?: string;
  due_date?: string; // flexible date string, same formats as create
  description?: string | null;
  // When provided, replaces the full member list. When omitted, members unchanged.
  member_ids?: string[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const { token } = getAccessToken();
  const url = `${getApiBaseUrl()}${path}`;
  console.log(`[api] ${init?.method ?? "GET"} ${url}`);
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  });

  console.log(`[api] response ${response.status} for ${url}`);

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    console.error(`[api] error body: ${text}`);
    if (response.status === 429) {
      throw new Error("Rate limited by Discord — please wait a moment and try again.");
    }
    throw new Error(`API error ${response.status}: ${text}`);
  }

  // 204 No Content — return undefined cast to T (callers that use void are fine).
  if (response.status === 204) return undefined as unknown as T;

  const data = await response.json();
  console.log(`[api] response body:`, JSON.stringify(data).slice(0, 500));
  return data as T;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function listDeadlines(days?: number): Promise<DeadlineResponse[]> {
  const query = days !== undefined ? `?days=${days}` : "";
  return apiFetch<DeadlineResponse[]>(`/deadlines${query}`);
}

export async function createDeadline(body: DeadlineCreateRequest): Promise<DeadlineResponse> {
  return apiFetch<DeadlineResponse>("/deadlines", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function editDeadline(id: number, body: DeadlineEditRequest): Promise<DeadlineResponse> {
  return apiFetch<DeadlineResponse>(`/deadlines/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteDeadline(id: number): Promise<void> {
  await apiFetch<void>(`/deadlines/${id}`, { method: "DELETE" });
}

export async function getAllMembers(): Promise<GuildMember[]> {
  console.log(`[api] getAllMembers`);
  return apiFetch<GuildMember[]>("/guild/members/all");
}

export async function searchMembers(query: string, limit = 10): Promise<GuildMember[]> {
  const params = new URLSearchParams({ query, limit: String(limit) });
  console.log(`[api] searchMembers query="${query}" limit=${limit}`);
  return apiFetch<GuildMember[]>(`/guild/members/search?${params}`);
}

export async function getMembers(ids: string[]): Promise<GuildMember[]> {
  console.log(`[api] getMembers ids=${JSON.stringify(ids)}`);
  if (ids.length === 0) {
    console.log(`[api] getMembers: empty ids, returning []`);
    return [];
  }
  const params = new URLSearchParams();
  ids.forEach((id) => params.append("ids", id));
  return apiFetch<GuildMember[]>(`/guild/members?${params}`);
}
