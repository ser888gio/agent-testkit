// Fetch helpers for the JSON API. All requests carry the browser session
// cookie; mutations echo the CSRF token from /api/session via x-csrf-token,
// which auth.require_admin compares against the session principal.

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

let csrfToken = "";

export function setCsrfToken(token: string) {
  csrfToken = token;
}

async function handle(response: Response): Promise<unknown> {
  if (response.status === 401) {
    // Session expired or absent: the server's /login flow sets a fresh one.
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
    throw new ApiError(401, "authentication required");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; the status text is the best we have.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

export async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const query = params ? "?" + new URLSearchParams(params).toString() : "";
  const response = await fetch(`/api${path}${query}`, {
    headers: { Accept: "application/json" },
  });
  return (await handle(response)) as T;
}

export async function apiSend<T>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(csrfToken ? { "x-csrf-token": csrfToken } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await handle(response)) as T;
}
