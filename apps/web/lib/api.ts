import { API_URL } from "./config";
import type { Answer, Claim, QueueItem } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type TokenGetter = () => Promise<string | null>;

async function request<T>(getToken: TokenGetter, path: string, init: RequestInit = {}): Promise<T> {
  const token = await getToken();
  if (!token) throw new ApiError(401, "Please sign in again.");
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Something went wrong.";
    throw new ApiError(res.status, res.status === 429 ? "You are going too fast. Please wait a moment." : detail);
  }
  return body as T;
}

export const makeApi = (getToken: TokenGetter) => ({
  listClaims: () => request<Claim[]>(getToken, "/v1/claims"),
  getClaim: (id: string) => request<Claim>(getToken, `/v1/claims/${encodeURIComponent(id)}`),
  createClaim: (policy_id: string, consent_given: boolean) =>
    request<Claim>(getToken, "/v1/claims", { method: "POST", body: JSON.stringify({ policy_id, consent_given }) }),
  upload: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ document_id: string }>(getToken, `/v1/claims/${encodeURIComponent(id)}/documents`, { method: "POST", body: fd });
  },
  submit: (id: string) => request<Claim>(getToken, `/v1/claims/${encodeURIComponent(id)}/submit`, { method: "POST" }),
  explain: (id: string, question: string) =>
    request<Answer>(getToken, `/v1/claims/${encodeURIComponent(id)}/explain`, { method: "POST", body: JSON.stringify({ question }) }),
  decide: (id: string, decision: string, note: string) =>
    request<Claim>(getToken, `/v1/claims/${encodeURIComponent(id)}/decision`, { method: "POST", body: JSON.stringify({ decision, note }) }),
  remove: (id: string) => request<void>(getToken, `/v1/claims/${encodeURIComponent(id)}`, { method: "DELETE" }),
  queue: () => request<QueueItem[]>(getToken, "/v1/reviewer/queue"),
});

export const humanStatus: Record<string, string> = {
  received: "Received",
  processing: "Being checked",
  ready: "Ready for review",
  needs_info: "More information needed",
  failed: "Could not be processed",
  decided: "Decided",
};
