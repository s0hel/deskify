/**
 * Thin fetch wrapper. The TYPED client is generated from the API's OpenAPI
 * schema (`npm run gen:api`) so the contract cannot silently drift from the
 * server (TDD §5.1). This file holds only what generation cannot: auth
 * headers, idempotency keys, and problem+json handling.
 */

export interface Denial {
  code: string;
  rule_key: string;
  scope: string;
  params: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly denials: Denial[] = [],
  ) {
    super(code);
  }
}

let accessToken: string | null = null;
export const setAccessToken = (t: string | null) => {
  accessToken = t;
};

export async function api<T>(
  path: string,
  init: RequestInit & { idempotencyKey?: string } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("content-type", "application/json");
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  // Generated when the USER ACTS, not when the request is sent, so a retry
  // across reconnects carries one key (TDD §11.3).
  if (init.idempotencyKey) headers.set("idempotency-key", init.idempotencyKey);

  const res = await fetch(`${import.meta.env.VITE_API_URL ?? ""}${path}`, {
    ...init,
    headers,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.code ?? "UNKNOWN", body.denials ?? []);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
