import "server-only";

import { getJson, normaliseBaseUrl, type RequestOptions } from "./client";

/**
 * Backend URL as seen from the Next.js server (e.g. http://api:8000 inside Docker).
 * Read at request time and never sent to the browser: no NEXT_PUBLIC_ prefix.
 */
function apiBaseUrl(): string {
  return normaliseBaseUrl(process.env.API_INTERNAL_URL ?? "http://localhost:8000");
}

export function serverGet<T>(path: string, options?: RequestOptions): Promise<T> {
  return getJson<T>(apiBaseUrl(), path, options);
}
