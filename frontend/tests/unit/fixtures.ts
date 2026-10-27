import type { HealthResponse, SystemInfo, SystemStatus } from "@/types/system";

export const healthyHealth: HealthResponse = {
  status: "ok",
  timestamp: "2026-10-27T20:00:00Z",
  components: {
    application: { status: "ok", critical: true, latency_ms: null, error: null },
    database: { status: "ok", critical: true, latency_ms: 2.5, error: null },
    redis: { status: "disabled", critical: false, latency_ms: null, error: null },
  },
};

export const databaseDownHealth: HealthResponse = {
  ...healthyHealth,
  status: "unavailable",
  components: {
    ...healthyHealth.components,
    database: {
      status: "unavailable",
      critical: true,
      latency_ms: null,
      error: "connection refused",
    },
  },
};

export const systemInfo: SystemInfo = {
  name: "ATLAS Global Bank",
  version: "0.1.0",
  environment: "development",
  build_sha: null,
  api_versions: ["v1"],
  python_version: "3.13.0",
  started_at: "2026-10-27T19:00:00Z",
  uptime_seconds: 3725,
  data_policy: "Synthetic simulation only.",
  modules: [
    { key: "ledger", name: "Ledger", phase: 3, status: "planned", description: "Double-entry GL" },
    {
      key: "platform",
      name: "Platform core",
      phase: 1,
      status: "available",
      description: "Health and config",
    },
  ],
};

export const systemStatus: SystemStatus = {
  status: "operational",
  timestamp: "2026-10-27T20:00:00Z",
  uptime_seconds: 3725,
  database: {
    connected: true,
    latency_ms: 2.5,
    error: null,
    server_version: "16.4",
    database_name: "atlas",
    table_count: 2,
    migrations: {
      current_revisions: ["0001_platform_baseline"],
      head_revisions: ["0001_platform_baseline"],
      up_to_date: true,
    },
    initialized_at: "2026-10-27T18:00:00Z",
  },
  redis: { status: "disabled", critical: false, latency_ms: null, error: null },
};

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Routes = Record<string, () => Response | Promise<Response>>;

/** Replaces global fetch with a router keyed by request path. */
export function mockApi(routes: Routes) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url, "http://localhost").pathname;
    const handler = routes[path];
    if (!handler) throw new Error(`Unexpected request to ${path}`);
    return handler();
  });
}

export const healthyRoutes: Routes = {
  "/api/health": () => jsonResponse(healthyHealth),
  "/api/system/info": () => jsonResponse(systemInfo),
  "/api/system/status": () => jsonResponse(systemStatus),
};
