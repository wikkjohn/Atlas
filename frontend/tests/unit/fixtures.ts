import type { CurrentUser, Permission } from "@/types/enterprise";
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

export interface RecordedRequest {
  method: string;
  path: string;
  search: URLSearchParams;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (request: RecordedRequest) => Response | Promise<Response>;
type Routes = Record<string, Handler>;

/**
 * Replaces global fetch with a router. Keys are "METHOD /path" or just "/path" (any method).
 * Every request is recorded in the returned `requests` array.
 */
export function mockApi(routes: Routes) {
  const requests: RecordedRequest[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const parsed = new URL(url, "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const request: RecordedRequest = {
      method,
      path: parsed.pathname,
      search: parsed.searchParams,
      headers: (init?.headers as Record<string, string>) ?? {},
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    requests.push(request);
    const handler = routes[`${method} ${parsed.pathname}`] ?? routes[parsed.pathname];
    if (!handler) throw new Error(`Unexpected request to ${method} ${parsed.pathname}`);
    return handler(request);
  });
  return Object.assign(spy, { requests });
}

const ALL_PERMISSIONS: Permission[] = [
  "countries:read",
  "countries:manage",
  "organizations:read",
  "organizations:manage",
  "employees:read",
  "employees:manage",
  "employees:read_compensation",
  "users:read",
  "users:manage",
  "audit:read",
  "customers:read",
  "customers:manage",
  "customers:review",
  "accounts:read",
  "accounts:request",
  "accounts:approve",
  "accounts:transact",
  "accounts:manage",
  "ledger:read",
  "ledger:post",
  "workflows:read",
  "workflows:start",
  "workflows:manage",
  "simulations:read",
  "simulations:run",
  "ai_tools:read",
  "ai_tools:manage",
  "ai_tools:invoke",
  "accounts:approve_low_risk",
];

function user(role: string, roleName: string, permissions: Permission[]): CurrentUser {
  return {
    id: `user-${role}`,
    username: role,
    email: `${role}@atlasbank.example`,
    display_name: `Demo ${roleName}`,
    role,
    role_name: roleName,
    employee_id: null,
    is_active: true,
    last_login_at: null,
    created_at: "2026-10-27T00:00:00Z",
    permissions,
  };
}

export const adminUser = user("platform_administrator", "Platform Administrator", ALL_PERMISSIONS);
export const employeeUser = user("banking_employee", "Banking Employee", [
  "countries:read",
  "organizations:read",
  "employees:read",
]);

export function authRoutes(current: CurrentUser): Routes {
  return { "GET /api/v1/auth/me": () => jsonResponse(current) };
}

export function page<T>(items: T[], total = items.length, limit = 50, offset = 0) {
  return { items, total, limit, offset };
}

export const healthyRoutes: Routes = {
  ...authRoutes(adminUser),
  "/api/health": () => jsonResponse(healthyHealth),
  "/api/system/info": () => jsonResponse(systemInfo),
  "/api/system/status": () => jsonResponse(systemStatus),
};
