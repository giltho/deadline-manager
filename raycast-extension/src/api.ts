import { getAccessToken } from "@raycast/utils";

const API_BASE_URL = "https://deadline-manager-production.up.railway.app";

// ── Types (mirroring api/schemas.py) ─────────────────────────────────────────

export interface DeadlineResponse {
  id: number;
  title: string;
  description: string | null;
  due_date: string; // ISO 8601 datetime string
  created_by: number;
  created_at: string; // ISO 8601 datetime string
  member_ids: number[];
}

export interface DeadlineCreateRequest {
  title: string;
  due_date: string; // flexible date string, e.g. "2026-06-15" or "15 Jun 2026 17:00"
  description?: string;
  member_ids?: number[];
}

export interface GuildMember {
  id: string;
  username: string;
  global_name: string | null;
  nick: string | null;
  avatar: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const { token } = getAccessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`API error ${response.status}: ${text}`);
  }

  return response.json() as Promise<T>;
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

export async function searchMembers(query: string, limit = 10): Promise<GuildMember[]> {
  const params = new URLSearchParams({ query, limit: String(limit) });
  return apiFetch<GuildMember[]>(`/guild/members/search?${params}`);
}

export async function getMembers(ids: number[]): Promise<GuildMember[]> {
  if (ids.length === 0) return [];
  const params = new URLSearchParams();
  ids.forEach((id) => params.append("ids", String(id)));
  return apiFetch<GuildMember[]>(`/guild/members?${params}`);
}
