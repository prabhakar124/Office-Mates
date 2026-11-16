/**
 * Minimal typed JSON client for the Office-Mates REST API.
 *
 * Pure (no Next.js imports) so it can be unit-tested; `server.ts` binds it to the
 * server-side backend URL. Errors from the API follow RFC 9457 Problem Details.
 */

import type { components } from "./schema";

export type Schemas = components["schemas"];

export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  request_id?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly problem?: ProblemDetail,
    options?: { cause?: unknown },
  ) {
    super(message, options);
    this.name = "ApiError";
  }

  /** True when the backend could not be reached at all (network error or timeout). */
  get unreachable(): boolean {
    return this.status === null;
  }
}

export interface RequestOptions {
  /** Abort the request after this many milliseconds. */
  timeoutMs?: number;
  /** Non-2xx statuses whose body should still be returned (e.g. 503 from /readyz). */
  acceptStatuses?: readonly number[];
  fetchImpl?: typeof fetch;
}

export function normaliseBaseUrl(raw: string): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`Invalid API base URL: ${raw}`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`API base URL must be http(s): ${raw}`);
  }
  return url.origin + url.pathname.replace(/\/+$/, "");
}

export async function getJson<T>(
  baseUrl: string,
  path: string,
  { timeoutMs = 3000, acceptStatuses = [], fetchImpl = fetch }: RequestOptions = {},
): Promise<T> {
  if (!path.startsWith("/")) {
    throw new Error(`API path must start with "/": ${path}`);
  }

  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}${path}`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
  } catch (err) {
    const reason = err instanceof Error && err.name === "TimeoutError" ? "timed out" : "failed";
    throw new ApiError(`Request to ${path} ${reason}`, null, undefined, { cause: err });
  }

  if (response.ok || acceptStatuses.includes(response.status)) {
    return (await response.json()) as T;
  }

  let problem: ProblemDetail | undefined;
  try {
    problem = (await response.json()) as ProblemDetail;
  } catch {
    problem = undefined;
  }
  throw new ApiError(
    problem?.detail ?? problem?.title ?? `Request to ${path} failed`,
    response.status,
    problem,
  );
}
