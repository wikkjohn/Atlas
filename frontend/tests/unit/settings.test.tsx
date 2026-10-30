import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { every } from "@/features/settings/JobsPanel";
import type { Role, UserAccount } from "@/types/enterprise";
import type { Job, JobSchedule } from "@/types/jobs";
import type { ObservabilityOverview, SlowQueryGroup } from "@/types/observability";
import type { HistoryOverview } from "@/types/simulations";

import { germany, japan } from "./enterprise-fixtures";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const roles: Role[] = [
  { id: "r1", code: "platform_administrator", name: "Platform Administrator", description: "", permissions: ["users:read", "users:manage", "accounts:approve"] },
  { id: "r2", code: "banking_employee", name: "Banking Employee", description: "", permissions: ["accounts:request"] },
  { id: "r3", code: "automated_policy", name: "Automated Policy Engine", description: "", permissions: ["accounts:approve_low_risk"] },
];

const account = (partial: Partial<UserAccount>): UserAccount => ({
  id: "u2",
  username: "teller",
  email: "teller@atlasbank.example",
  display_name: "Demo Teller",
  role: "banking_employee",
  role_name: "Banking Employee",
  employee_id: null,
  is_active: true,
  last_login_at: null,
  created_at: "2026-10-27T00:00:00Z",
  is_service_account: false,
  ...partial,
});

const job = (partial: Partial<Job>): Job => ({
  id: "job-1",
  job_number: 41,
  kind: "ledger.reconcile",
  payload: { mode: "incremental" },
  status: "succeeded",
  attempts: 1,
  max_attempts: 2,
  run_at: "2026-10-29T10:00:00Z",
  result: { ok: true, duration_ms: 1840 },
  last_error: null,
  locked_by: null,
  schedule_name: "ledger-incremental-reconciliation",
  created_by_username: null,
  created_at: "2026-10-29T10:00:00Z",
  started_at: "2026-10-29T10:00:00Z",
  finished_at: "2026-10-29T10:00:02Z",
  ...partial,
});

const schedules: JobSchedule[] = [
  {
    id: "s1",
    name: "ledger-incremental-reconciliation",
    description: "Check what was posted since the last reconciliation",
    kind: "ledger.reconcile",
    payload: { mode: "incremental" },
    interval_seconds: 900,
    enabled: true,
    business_calendar: null,
    next_run_at: "2026-10-29T10:15:00Z",
    last_job: job({}),
  },
  {
    id: "s2",
    name: "loan-servicing",
    description: "Service the loan book up to today",
    kind: "lending.service_loans",
    payload: {},
    interval_seconds: 86_400,
    enabled: false,
    business_calendar: "DE",
    next_run_at: "2026-10-29T10:00:00Z",
    last_job: null,
  },
];

const observability: ObservabilityOverview = {
  process: { version: "0.15.0", pid: 42, uptime_seconds: 3600, jobs_execution: "worker", slow_query_ms: 250 },
  requests: [
    { method: "GET", route: "/api/v1/customers", count: 120, errors: 0, by_status: { "2xx": 120 }, avg_ms: 21, p50_ms: 18, p95_ms: 43, max_ms: 90 },
    { method: "POST", route: "/api/v1/simulations", count: 3, errors: 1, by_status: { "2xx": 2, "5xx": 1 }, avg_ms: 80, p50_ms: 70, p95_ms: 140, max_ms: 140 },
  ],
  queue: { due: 4, scheduled_later: 2, running: 1, oldest_due_seconds: 95 },
  throughput: [{ kind: "simulation.execute", finished: 6, succeeded: 5, failed: 1, per_minute: 0.1, avg_ms: 18_500, p95_ms: 30_000, max_ms: 31_000 }],
  workers: [
    { name: "host:101:1", hostname: "host", pid: 101, state: "running", started_at: "2026-10-29T09:00:00Z", last_seen_at: "2026-10-29T10:00:00Z", stopped_at: null, succeeded: 12, failed: 1, retried: 2, current_job_kind: "simulation.execute" },
    { name: "host:102:1", hostname: "host", pid: 102, state: "lost", started_at: "2026-10-29T09:00:00Z", last_seen_at: "2026-10-29T09:10:00Z", stopped_at: null, succeeded: 3, failed: 0, retried: 0, current_job_kind: null },
  ],
  database: { size_bytes: 2_400_000_000, connections: 9, cache_hit_percent: 99.2 },
};

const slowQueries: SlowQueryGroup[] = [
  { statement: "SELECT count(*) FROM workflow_events_simulation", context: "job simulation.archive_history", count: 2, avg_ms: 400, max_ms: 500, total_ms: 800, last_seen: "2026-10-29T10:00:00Z" },
];

const history: HistoryOverview = {
  partitions: [
    { table: "workflow_events", realm: "live", rows_estimate: 1365, bytes: 516_096 },
    { table: "workflow_events", realm: "simulation", rows_estimate: 5_129_739, bytes: 2_200_000_000 },
  ],
  runs_by_history_state: { present: 3, archived: 1, purged: 0 },
  archive_directory: "/app/var/simulation-archive",
  archive_bytes: 543_679_738,
  recent_archives: [
    { id: "a1", run_id: "run-1", run_number: 7, kind: "archive", location: "run-000007-x", rows: 6_807_087, bytes: 543_679_738, tables: { workflow_events: 5_129_739 }, created_by_username: "researcher", created_at: "2026-10-29T10:00:00Z" },
  ],
  retention_schedule_enabled: false,
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/observability/overview": () => jsonResponse(observability),
  "GET /api/v1/observability/slow-queries": () => jsonResponse(slowQueries),
  "GET /api/v1/simulations/history": () => jsonResponse(history),
  "GET /api/v1/job-schedules": () => jsonResponse(schedules),
  "GET /api/v1/countries": () => jsonResponse(page([germany, japan])),
  "GET /api/v1/jobs": () =>
    jsonResponse(
      page([
        job({}),
        job({ id: "job-2", job_number: 42, kind: "simulation.execute", status: "failed", result: null, last_error: "RuntimeError: boom", schedule_name: null, created_by_username: "researcher" }),
      ]),
    ),
  "GET /api/v1/roles": () => jsonResponse(roles),
  "GET /api/v1/users": (r: { search: URLSearchParams }) =>
    jsonResponse(
      page(
        r.search.get("kind") === "service"
          ? [account({ id: "u3", username: "atlas-policy-engine", display_name: "ATLAS Policy Engine (system)", role: "automated_policy", role_name: "Automated Policy Engine", is_service_account: true })]
          : [account({})],
      ),
    ),
};

describe("System Settings users and roles", () => {
  it("shows background job schedules and lets an administrator switch and run them", async () => {
    const api = mockApi({
      ...routes,
      "PATCH /api/v1/job-schedules/loan-servicing": () => jsonResponse({ ...schedules[1], enabled: true }),
      "POST /api/v1/job-schedules/ledger-incremental-reconciliation/run": () => jsonResponse(job({ id: "job-3", job_number: 43, status: "queued" }), 202),
    });
    renderApp("/settings");

    const table = await screen.findByRole("table", { name: "Job schedules" });
    const recon = (await within(table).findByText("ledger-incremental-reconciliation")).closest("tr") as HTMLElement;
    expect(within(recon).getByText("every 15 min")).toBeInTheDocument();
    expect(within(recon).getByText("Succeeded")).toBeInTheDocument();
    const servicing = within(table).getByText("loan-servicing").closest("tr") as HTMLElement;
    expect(within(servicing).getByText("Off")).toBeInTheDocument();
    const recent = screen.getByRole("table", { name: "Recent jobs" });
    expect(await within(recent).findByText("RuntimeError: boom")).toBeInTheDocument();
    expect(within(recent).getByText("1.8 s")).toBeInTheDocument();

    await userEvent.click(within(servicing).getByLabelText("Enable loan-servicing"));
    await userEvent.click(within(recon).getByRole("button", { name: "Run ledger-incremental-reconciliation now" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(2));
    const patch = api.requests.find((r) => r.method === "PATCH");
    expect(patch?.body).toEqual({ enabled: true });
  });

  it("lets an administrator run a schedule on a country's business days", async () => {
    const api = mockApi({
      ...routes,
      "PATCH /api/v1/job-schedules/ledger-incremental-reconciliation": () => jsonResponse({ ...schedules[0], business_calendar: "JP" }),
      "PATCH /api/v1/job-schedules/loan-servicing": () => jsonResponse({ ...schedules[1], business_calendar: null }),
    });
    renderApp("/settings");

    const table = await screen.findByRole("table", { name: "Job schedules" });
    const recon = await within(table).findByLabelText("Business calendar of ledger-incremental-reconciliation");
    const servicing = within(table).getByLabelText("Business calendar of loan-servicing");
    await waitFor(() => expect(servicing).toHaveValue("DE"));
    expect(recon).toHaveValue("");
    await userEvent.selectOptions(recon, "Japan");
    await userEvent.selectOptions(servicing, "Every day");
    await waitFor(() => expect(api.requests.filter((r) => r.method === "PATCH")).toHaveLength(2));
    expect(api.requests.filter((r) => r.method === "PATCH").map((r) => r.body)).toEqual([{ business_calendar: "JP" }, { business_calendar: "" }]);
  });

  it("shows request latency, the job queue, workers and slow queries", async () => {
    mockApi(routes);
    renderApp("/settings");

    const panel = await screen.findByRole("region", { name: "Observability" });
    expect(await within(panel).findByText("oldest waiting 1m 35s")).toBeInTheDocument();
    const workers = within(panel).getByRole("table", { name: "Workers" });
    const lost = within(workers).getByText("host:102:1").closest("tr") as HTMLElement;
    expect(within(lost).getByText("Lost")).toBeInTheDocument();
    expect(within(workers).getByText("simulation.execute")).toBeInTheDocument();
    const throughput = within(panel).getByRole("table", { name: "Job throughput" });
    expect(within(throughput).getByText("18.5 s")).toBeInTheDocument();
    const requests = within(panel).getByRole("table", { name: "Request latency" });
    expect(within(requests).getByText("GET /api/v1/customers")).toBeInTheDocument();
    const slow = await within(panel).findByRole("table", { name: "Slow queries" });
    expect(within(slow).getByText(/job simulation.archive_history/)).toBeInTheDocument();
    expect(within(slow).getByText(/2× · avg 400 ms · max 500 ms/)).toBeInTheDocument();
  });

  it("shows where workflow history is stored and what was archived", async () => {
    mockApi(routes);
    renderApp("/settings");

    const panel = await screen.findByRole("region", { name: "Simulation history" });
    const partitions = await within(panel).findByRole("table", { name: "History partitions" });
    const events = within(partitions).getByText("Events").closest("tr") as HTMLElement;
    expect(within(events).getByText("1,365 rows · 504 KB")).toBeInTheDocument();
    expect(within(events).getByText("5,129,739 rows · 2.0 GB")).toBeInTheDocument();
    const archives = within(panel).getByRole("table", { name: "Recent archives" });
    expect(within(archives).getByText("6,807,087 rows · 518 MB")).toBeInTheDocument();
    expect(within(panel).getByText(/Automatic archiving of runs older than 30 days is off/)).toBeInTheDocument();
  });

  it("describes schedule intervals in words", () => {
    expect([every(60), every(900), every(3600), every(7200), every(86_400)]).toEqual([
      "every minute",
      "every 15 min",
      "hourly",
      "every 2 h",
      "daily",
    ]);
  });

  it("lets an administrator change roles, deactivate users and create accounts", async () => {
    const api = mockApi({
      ...routes,
      "PATCH /api/v1/users/u2": () => jsonResponse(account({ role: "platform_administrator" })),
      "POST /api/v1/users": () => jsonResponse(account({ id: "u9", username: "new.analyst" }), 201),
    });
    renderApp("/settings");

    const users = await screen.findByRole("table", { name: "Users" });
    const role = await within(users).findByLabelText("Role of teller");
    // Service roles are never offered to people.
    expect(within(role).queryByRole("option", { name: "Automated Policy Engine" })).toBeNull();
    await userEvent.selectOptions(role, "platform_administrator");
    await waitFor(() => expect(api.requests.find((r) => r.method === "PATCH")?.body).toEqual({ role: "platform_administrator" }));
    await userEvent.click(within(users).getByRole("button", { name: "Deactivate teller" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method === "PATCH").at(-1)?.body).toEqual({ is_active: false }));

    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    const form = await screen.findByRole("form", { name: "Create a user" });
    const submit = within(screen.getByRole("dialog")).getByRole("button", { name: "Create user" });
    await userEvent.type(within(form).getByLabelText("Username"), "New Analyst");
    await userEvent.type(within(form).getByLabelText("Initial password"), "short");
    await userEvent.click(submit);
    expect(within(form).getByText(/lower-case letters/)).toBeInTheDocument();
    expect(within(form).getByText("At least 12 characters.")).toBeInTheDocument();
    expect(api.requests.some((r) => r.method === "POST")).toBe(false);

    await userEvent.clear(within(form).getByLabelText("Username"));
    await userEvent.type(within(form).getByLabelText("Username"), "new.analyst");
    await userEvent.type(within(form).getByLabelText("Email"), "new.analyst@atlasbank.example");
    await userEvent.type(within(form).getByLabelText("Display name"), "New Analyst");
    await userEvent.type(within(form).getByLabelText("Initial password"), "-a-long-enough-password");
    await userEvent.click(submit);
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      username: "new.analyst",
      email: "new.analyst@atlasbank.example",
      role: "banking_employee",
    });
  });

  it("shows service accounts read-only apart from activation", async () => {
    mockApi(routes);
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("tab", { name: "Service accounts" }));
    const users = screen.getByRole("table", { name: "Users" });
    expect(await within(users).findByText("ATLAS Policy Engine (system)")).toBeInTheDocument();
    expect(within(users).queryByLabelText("Role of atlas-policy-engine")).toBeNull();
    expect(within(users).getByText("Cannot sign in")).toBeInTheDocument();
    expect(within(users).getByRole("button", { name: "Deactivate atlas-policy-engine" })).toBeInTheDocument();
  });

  it("shows the role and permission matrix to everyone, users only with permission", async () => {
    mockApi({ ...routes, ...authRoutes(employeeUser) });
    renderApp("/settings");
    const matrix = await screen.findByRole("table", { name: "Role permissions" });
    expect(within(matrix).getByLabelText("Automated Policy Engine: accounts:approve_low_risk")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Users" })).not.toBeInTheDocument();
  });
});
