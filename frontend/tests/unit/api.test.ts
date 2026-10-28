import { ApiError, apiGet, BackendUnreachableError, getHealth } from "@/services/api";

import { healthyHealth, jsonResponse, mockApi } from "./fixtures";

describe("API client", () => {
  it("parses the backend error envelope into ApiError", async () => {
    mockApi({
      "/api/missing": () =>
        jsonResponse(
          {
            error: {
              code: "not_found",
              message: "Not Found",
              details: null,
              correlation_id: "abc-123",
            },
          },
          404,
        ),
    });

    const error = await apiGet("/api/missing").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: "not_found",
      message: "Not Found",
      correlationId: "abc-123",
    });
  });

  it("raises BackendUnreachableError on network failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(apiGet("/api/system/info")).rejects.toBeInstanceOf(BackendUnreachableError);
  });

  it("returns the health report even when the API answers 503", async () => {
    const report = { ...healthyHealth, status: "unavailable" };
    mockApi({ "/api/health": () => jsonResponse(report, 503) });

    await expect(getHealth()).resolves.toEqual(report);
  });
});
