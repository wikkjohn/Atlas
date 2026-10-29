import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CaseResult, Profile, Scenario, SimulationRunDetail } from "@/types/simulations";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const scenario: Scenario = {
  scenario_id: "retail-onboarding",
  version: 1,
  name: "Retail account onboarding",
  description: "A working day of synthetic retail applications.",
  workload: "retail_onboarding",
  workflow_id: "WF-0001",
  workflow_version: 1,
  modes: ["baseline"],
  simulated_start: "2026-01-05T09:00:00Z",
  config: {},
};

const profiles: Profile[] = [
  { profile_id: "small", name: "Small test", applications: 100, customers: 100, employees: 25, status: "verified", runnable: true, note: "" },
  { profile_id: "department", name: "Department test", applications: 10000, customers: 10000, employees: 500, status: "verified", runnable: true, note: "" },
  { profile_id: "enterprise", name: "Future enterprise scale", applications: 1000000, customers: 1000000, employees: 150000, status: "target", runnable: false, note: "A configuration target only." },
];

const completed: SimulationRunDetail = {
  id: "run-1",
  run_number: 7,
  scenario_id: "retail-onboarding",
  scenario_version: 1,
  workflow_id: "WF-0001",
  workflow_version: 1,
  profile: "small",
  seed: 42,
  applications: 100,
  employees: 25,
  status: "completed",
  failure_reason: null,
  software_version: "0.1.0",
  config_hash: "abcdef0123456789abcdef",
  result_digest: "0123456789abcdef0123",
  created_by_username: "researcher",
  created_at: "2026-10-28T09:00:00Z",
  started_at: "2026-10-28T09:00:01Z",
  completed_at: "2026-10-28T09:00:25Z",
  wall_ms: 24000,
  progress: { cases_total: 100, cases_started: 100, cases_completed: 100, events_processed: 290 },
  percent_complete: 100,
  mode: "baseline",
  tool_id: null,
  tool_version: null,
  batch_id: null,
  config: {},
  results: {
    cases: 100,
    completed: 100,
    unfinished: 0,
    outcomes: { approved: 86, rejected: 14 },
    by_kind: {
      clean: { cases: 70, approved: 69, rejected: 1, other: 0 },
      sanctions_hit: { cases: 4, approved: 1, rejected: 3, other: 0 },
    },
    risk_ratings: { low: 80, medium: 12, high: 8 },
    ground_truth: { correct: 98, false_approvals: 1, false_rejections: 1, accuracy: 0.98 },
    manual_reviews: 92,
    straight_through_rate: 0.08,
    review_labor_hours: 21,
    overdue_tasks: 0,
    cycle_time_hours: { avg: 2.8, p50: 0.25, p95: 5.4, max: 72 },
    review_queue_wait_hours: { avg: 0.1, p95: 0.5 },
    staff: { tellers: 10 },
    simulated_hours: 79.4,
    execution: { events_processed: 290, workflow_steps_completed: 1466, wall_ms: 24000, cases_per_second: 4.2 },
  },
  simulated_start: "2026-01-05T09:00:00Z",
  simulated_end: "2026-01-08T16:23:00Z",
  staff_unit_id: "org-1",
  reproductions: [{ id: "run-0", run_number: 6, result_digest: "0123456789abcdef0123", matches: true }],
  history_state: "present",
  archive: null,
};

const mismatch: CaseResult = {
  case_index: 3,
  execution_id: "exe-3",
  kind: "sanctions_hit",
  expected_outcome: "rejected",
  status: "completed",
  outcome: "approved",
  matches_ground_truth: false,
  risk_rating: "high",
  flags: ["sanctions_hit"],
  manual_reviews: 1,
  review_minutes: 31.5,
  queue_wait_minutes: 4,
  overdue_tasks: 0,
  arrived_at: "2026-01-05T10:00:00Z",
  completed_at: "2026-01-05T10:40:00Z",
  cycle_hours: 0.667,
  path: ["receive_application", "complete"],
  ai_recommendation: null,
  ai_status: null,
  automated: false,
};

const baseRoutes = {
  ...healthyRoutes,
  "GET /api/v1/simulations/scenarios": () => jsonResponse([scenario]),
  "GET /api/v1/simulations/profiles": () => jsonResponse(profiles),
  "GET /api/v1/simulations": () => jsonResponse(page([completed])),
  "GET /api/v1/simulations/run-1": () => jsonResponse(completed),
  "GET /api/v1/simulations/run-1/cases": () => jsonResponse(page([mismatch])),
  "GET /api/v1/ai-tools": () => jsonResponse(page([])),
};

describe("Simulation Center", () => {
  it("starts a run with the chosen workload and seed", async () => {
    const queued = { ...completed, id: "run-2", run_number: 8, status: "queued", results: null, reproductions: [], percent_complete: 0, progress: { cases_total: 40 } };
    const api = mockApi({
      ...baseRoutes,
      "POST /api/v1/simulations": () => jsonResponse(queued, 202),
      "GET /api/v1/simulations/run-2": () => jsonResponse(queued),
    });
    renderApp("/simulations");

    const form = await screen.findByRole("form", { name: "Start a simulation" });
    const enterprise = await within(form).findByRole("option", { name: /Future enterprise scale/ });
    expect(enterprise).toBeDisabled();

    await userEvent.selectOptions(within(form).getByLabelText("Workload"), "custom");
    await userEvent.clear(within(form).getByLabelText("Cases"));
    await userEvent.type(within(form).getByLabelText("Cases"), "40");
    await userEvent.clear(within(form).getByLabelText("Random seed"));
    await userEvent.type(within(form).getByLabelText("Random seed"), "1234");
    await userEvent.click(within(form).getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({
      scenario_id: "retail-onboarding",
      scenario_version: 1,
      mode: "baseline",
      tool_id: null,
      tool_version: null,
      profile: "custom",
      seed: 1234,
      applications: 40,
      employees: 10,
    });
    expect(await screen.findByRole("progressbar", { name: "Run #8 progress" })).toBeInTheDocument();
  });

  it("retries a failed start with the same Idempotency-Key, then uses a fresh one", async () => {
    const queued = { ...completed, id: "run-2", run_number: 8, status: "queued", results: null, reproductions: [], percent_complete: 0, progress: { cases_total: 50 } };
    let attempts = 0;
    const api = mockApi({
      ...baseRoutes,
      "POST /api/v1/simulations": () =>
        ++attempts === 1
          ? jsonResponse({ error: { code: "conflict", message: "Simulation run #7 is still in progress." } }, 409)
          : jsonResponse(queued, 202),
      "GET /api/v1/simulations/run-2": () => jsonResponse(queued),
    });
    renderApp("/simulations");
    const form = await screen.findByRole("form", { name: "Start a simulation" });
    const start = within(form).getByRole("button", { name: "Start run" });

    await userEvent.click(start);
    expect(await screen.findByText(/still in progress/)).toBeInTheDocument();
    await userEvent.click(start);
    await screen.findByRole("progressbar", { name: "Run #8 progress" });
    await userEvent.click(start);
    await waitFor(() => expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(3));

    const keys = api.requests.filter((r) => r.method === "POST").map((r) => r.headers["Idempotency-Key"]);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]); // the retry of the same start
    expect(keys[2]).not.toBe(keys[0]); // a new start after success
  });

  it("rejects an invalid seed before sending anything", async () => {
    const api = mockApi(baseRoutes);
    renderApp("/simulations");
    const form = await screen.findByRole("form", { name: "Start a simulation" });
    await userEvent.clear(within(form).getByLabelText("Random seed"));
    await userEvent.type(within(form).getByLabelText("Random seed"), "-3");
    expect(within(form).getByText("A whole number from 0 upwards.")).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Start run" })).toBeDisabled();
    expect(api.requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("shows outcomes, ground truth, reproducibility and mismatched cases", async () => {
    mockApi(baseRoutes);
    renderApp("/simulations?run=run-1");

    expect(await screen.findByRole("heading", { name: "Run #7" })).toBeInTheDocument();
    expect(screen.getByText("98.0%")).toBeInTheDocument();
    expect(screen.getByText("1 false approvals · 1 false rejections")).toBeInTheDocument();
    expect(screen.getByText("Run #6: identical results")).toBeInTheDocument();
    const byKind = screen.getByRole("table", { name: "Outcomes by case type" });
    expect(within(byKind).getByText("Sanctions hit")).toBeInTheDocument();
    const cases = await screen.findByRole("table", { name: "Case results" });
    expect(within(cases).getByLabelText("Differs from ground truth")).toBeInTheDocument();
  });

  it("reports why a run failed", async () => {
    const failed = { ...completed, status: "failed", results: null, failure_reason: "No active 'Retail Banking' division exists." };
    mockApi({ ...baseRoutes, "GET /api/v1/simulations/run-1": () => jsonResponse(failed) });
    renderApp("/simulations?run=run-1");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No active 'Retail Banking' division exists.");
  });

  it("lets read-only roles review runs without starting them", async () => {
    const reader = { ...employeeUser, permissions: [...employeeUser.permissions, "simulations:read" as const] };
    mockApi({ ...baseRoutes, ...authRoutes(reader) });
    renderApp("/simulations");
    expect(await screen.findByText("Your role can review runs but not start them.")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Start a simulation" })).not.toBeInTheDocument();
    expect(await screen.findByText("Run #7")).toBeInTheDocument();
  });

  it("archives a run's workflow history and offers to restore it", async () => {
    let state: "present" | "archived" = "present";
    const archived = {
      ...completed,
      history_state: "archived" as const,
      archive: { id: "a1", run_id: "run-1", run_number: 7, kind: "archive" as const, location: "run-000007-x", rows: 1_234, bytes: 56_789, tables: { workflow_events: 900 }, created_by_username: "admin", created_at: "2026-10-29T10:00:00Z" },
    };
    const api = mockApi({
      ...baseRoutes,
      "GET /api/v1/simulations/run-1": () => jsonResponse(state === "present" ? completed : archived),
      "POST /api/v1/simulations/run-1/archive": () => {
        state = "archived";
        return jsonResponse({ job_id: "job-9", job_number: 9, kind: "simulation.archive_history", status: "queued" }, 202);
      },
    });
    renderApp("/simulations?run=run-1");

    const history = await screen.findByRole("region", { name: "Workflow history" });
    await userEvent.click(within(history).getByRole("button", { name: "Archive history" }));

    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(await within(history).findByText(/1,234 rows in 55 KB of files/)).toBeInTheDocument();
    expect(within(history).getByRole("button", { name: "Restore history" })).toBeInTheDocument();
    expect(within(history).queryByRole("status")).not.toBeInTheDocument(); // the job finished
    // Results and case outcomes stay.
    expect(screen.getByRole("table", { name: "Case results" })).toBeInTheDocument();
  });
});
