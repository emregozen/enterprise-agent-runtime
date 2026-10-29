import { presentText } from "./errors";

let csrfToken: string | null = null;
let activeGroupId: string | null = null;

export function setApiAuthContext(ctx: { csrfToken?: string | null; activeGroupId?: string | null }) {
  if (ctx.csrfToken !== undefined) csrfToken = ctx.csrfToken;
  if (ctx.activeGroupId !== undefined) activeGroupId = ctx.activeGroupId;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD" && !csrfToken && !path.startsWith("/api/auth/")) {
    try {
      const meRes = await fetch("/backend/api/auth/me", { headers: { Accept: "application/json" } });
      if (meRes.ok) {
        const meBody = (await meRes.json()) as { csrf_token?: string | null; active_group_id?: string | null };
        if (meBody.csrf_token) csrfToken = meBody.csrf_token;
        if (meBody.active_group_id) activeGroupId = meBody.active_group_id;
      }
    } catch {
      /* ignore */
    }
  }
  const doFetch = () => {
    const extraHeaders: Record<string, string> = {};
    if (csrfToken) extraHeaders["X-CSRF-Token"] = csrfToken;
    if (activeGroupId) extraHeaders["X-Active-Group"] = activeGroupId;
    return fetch(`/backend${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...extraHeaders,
        ...init?.headers,
      },
    });
  };
  let response = await doFetch();
  if (response.status === 403 && method !== "GET" && !path.startsWith("/api/auth/")) {
    try {
      const meRes = await fetch("/backend/api/auth/me", { headers: { Accept: "application/json" } });
      if (meRes.ok) {
        const meBody = (await meRes.json()) as { csrf_token?: string | null; active_group_id?: string | null };
        if (meBody.csrf_token && meBody.csrf_token !== csrfToken) {
          csrfToken = meBody.csrf_token;
          if (meBody.active_group_id) activeGroupId = meBody.active_group_id;
          response = await doFetch();
        }
      }
    } catch {
      /* ignore */
    }
  }
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(presentText(detail), response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
