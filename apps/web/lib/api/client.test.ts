import { describe, expect, it, vi } from "vitest";

import { ApiError, getJson, normaliseBaseUrl } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("normaliseBaseUrl", () => {
  it("strips trailing slashes", () => {
    expect(normaliseBaseUrl("http://api:8000/")).toBe("http://api:8000");
    expect(normaliseBaseUrl("https://example.test/base//")).toBe("https://example.test/base");
  });

  it("rejects non-http URLs and garbage", () => {
    expect(() => normaliseBaseUrl("file:///etc/passwd")).toThrow(/http\(s\)/);
    expect(() => normaliseBaseUrl("not a url")).toThrow(/Invalid/);
  });
});

describe("getJson", () => {
  it("returns parsed JSON on success", async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ status: "ok" }));
    await expect(getJson("http://api", "/healthz", { fetchImpl })).resolves.toEqual({
      status: "ok",
    });
    expect(fetchImpl).toHaveBeenCalledWith("http://api/healthz", expect.anything());
  });

  it("returns the body for explicitly accepted error statuses", async () => {
    const body = { status: "fail", checks: [] };
    const fetchImpl = vi.fn(async () => jsonResponse(body, 503));
    await expect(
      getJson("http://api", "/readyz", { fetchImpl, acceptStatuses: [503] }),
    ).resolves.toEqual(body);
  });

  it("raises ApiError with the problem details for other errors", async () => {
    const problem = {
      type: "https://officemates.local/problems/not-found",
      title: "Resource not found",
      status: 404,
      detail: "Document 1 does not exist",
      request_id: "abc12345",
    };
    const fetchImpl = vi.fn(async () => jsonResponse(problem, 404));
    const err = (await getJson("http://api", "/documents/1", { fetchImpl }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe("Document 1 does not exist");
    expect(err.problem?.request_id).toBe("abc12345");
    expect(err.unreachable).toBe(false);
  });

  it("marks network failures as unreachable", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const err = (await getJson("http://api", "/healthz", { fetchImpl }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.unreachable).toBe(true);
  });

  it("rejects relative paths without a leading slash", async () => {
    await expect(getJson("http://api", "healthz")).rejects.toThrow(/must start/);
  });
});
