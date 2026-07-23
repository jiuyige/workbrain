import { afterEach, vi } from "vitest";

import { clearAuthSession, setActiveOrganizationId, setAuthSession } from "../auth/session";
import { ApiError, apiRequest } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  clearAuthSession();
});

describe("apiRequest", () => {
  it("adds JWT and organization headers to API requests", async () => {
    setAuthSession("signed-jwt");
    setActiveOrganizationId(7);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await apiRequest<{ status: string }>("/health");

    expect(response).toEqual({ status: "ok" });
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(options.headers);
    expect(url).toBe("/api/health");
    expect(headers.get("Authorization")).toBe("Bearer signed-jwt");
    expect(headers.get("X-Organization-ID")).toBe("7");
  });

  it("turns the backend error envelope into an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: "FORBIDDEN",
            message: "organization access denied",
            request_id: "request-123",
          }),
          { status: 403, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(apiRequest("/organizations/1")).rejects.toEqual(
      new ApiError(
        403,
        "FORBIDDEN",
        "organization access denied",
        "request-123",
      ),
    );
  });

  it("returns undefined for a successful response without content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );

    await expect(
      apiRequest<void>("/service-requests/1/cancel", { method: "POST" }),
    ).resolves.toBeUndefined();
  });

  it("uses a safe fallback when an error response is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("upstream unavailable", {
          status: 502,
          headers: { "Content-Type": "text/plain" },
        }),
      ),
    );

    await expect(apiRequest("/assistant/service-tools")).rejects.toEqual(
      new ApiError(502, "HTTP_ERROR", "request failed", null),
    );
  });
});
