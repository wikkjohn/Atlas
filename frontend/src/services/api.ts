import type { ApiErrorBody, HealthResponse, SystemInfo, SystemStatus } from "@/types/system";

// Empty by default: the browser calls the same origin and the Vite dev server (or a
// reverse proxy in other environments) forwards /api to the backend.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

/** The backend answered, but with an error status. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string | null;
  readonly details: unknown;

  constructor(status: number, body: Partial<ApiErrorBody> | null) {
    super(body?.error?.message ?? `Request failed with HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.error?.code ?? "http_error";
    this.correlationId = body?.error?.correlation_id ?? null;
    this.details = body?.error?.details;
  }
}

/** The backend could not be reached at all (server down, proxy error, network failure). */
export class BackendUnreachableError extends Error {
  constructor(cause: unknown) {
    super("The ATLAS API could not be reached.", { cause });
    this.name = "BackendUnreachableError";
  }
}

async function request(path: string): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, { headers: { Accept: "application/json" } });
  } catch (cause) {
    throw new BackendUnreachableError(cause);
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return typeof value === "object" && value !== null && "error" in value;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await request(path);
  const body = await readJson(response);
  if (!response.ok) {
    // The Vite proxy answers 502/504 with no JSON body when the backend is down.
    if (!isApiErrorBody(body) && [502, 503, 504].includes(response.status)) {
      throw new BackendUnreachableError(new Error(`HTTP ${response.status}`));
    }
    throw new ApiError(response.status, isApiErrorBody(body) ? body : null);
  }
  return body as T;
}

/** Health returns 503 *with a health report* when the database is down; that is data. */
export async function getHealth(): Promise<HealthResponse> {
  const response = await request("/api/health");
  const body = await readJson(response);
  if (body && typeof body === "object" && "components" in body) {
    return body as HealthResponse;
  }
  if ([502, 503, 504].includes(response.status) || body === null) {
    throw new BackendUnreachableError(new Error(`HTTP ${response.status}`));
  }
  throw new ApiError(response.status, isApiErrorBody(body) ? body : null);
}

export const getSystemInfo = () => apiGet<SystemInfo>("/api/system/info");
export const getSystemStatus = () => apiGet<SystemStatus>("/api/system/status");
