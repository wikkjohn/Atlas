import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { AiTool } from "@/types/aiTools";
import type { BenchmarkRow, Comparison, ExperimentDetail } from "@/types/experiments";
import { DEFAULT_COSTS, DEFAULT_THRESHOLDS } from "@/types/experiments";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const row = (metric: string, label: string, unit: Comparison["unit"], baseline: number, candidate: number, extra: Partial<Comparison> = {}): Comparison => ({
  metric,
  label,
  unit,
  better: "lower",
  baseline,
  candidate,
  delta: candidate - baseline,
  relative_change: baseline ? (candidate - baseline) / baseline : null,
  improved: candidate < baseline,
  regression: false,
  ...extra,
});

const sideCosts = (review: number, ai: number) => ({
  inputs: {},
  lines: {
    ai_execution: ai,
    automation_oversight: 0,
    exception_handling: 36,
    infrastructure: 22,
    manual_escalation: 54,
    review_labour: review,
  },
  operating_total: review + ai + 112,
  cost_per_completed_case: (review + ai + 112) / 100,
  risk_exposure: {},
  risk_exposure_total: 120,
});

const metrics = (role: "baseline" | "candidate") => ({
  cases: 100,
  completed: 100,
  manual_reviews: role === "baseline" ? 92 : 12,
  automated_approvals: role === "baseline" ? 0 : 80,
  escalations: 9,
  exceptions: 3,
  false_approvals: 0,
  false_rejections: role === "baseline" ? 2 : 0,
  decisions_checked: 89,
  policy_violations: 0,
  result_digest: "abc",
  cycle_seconds: { avg: role === "baseline" ? 10116 : 9501, p50: 600, p95: 19586 },
  ai: { invocations: 96, blocked: 0, errors: 0, by_status: { succeeded: 96 } },
  workload: { seed: 42, applications: 100, employees: 25, software_version: "0.7.0" },
});

const experiment: ExperimentDetail = {
  id: "exp-1",
  experiment_number: 3,
  name: "KYC assistant vs. baseline",
  scenario_id: "retail-onboarding",
  scenario_version: 2,
  candidate_mode: "ai_automated",
  tool_id: "agb-intelligent-kyc-assistant",
  tool_version: "1.0.0",
  status: "completed",
  failure_reason: null,
  verdict: "not_successful",
  created_by_username: "researcher",
  created_at: "2026-10-28T10:00:00Z",
  completed_at: "2026-10-28T10:01:00Z",
  baseline: { id: "run-a", run_number: 5, mode: "baseline", status: "completed", percent_complete: 100, failure_reason: null },
  candidate: { id: "run-c", run_number: 6, mode: "ai_automated", status: "completed", percent_complete: 100, failure_reason: null },
  headline: { labour_hours: -0.774 },
  configuration: { costs: DEFAULT_COSTS, thresholds: DEFAULT_THRESHOLDS },
  configuration_hash: "0123456789abcdef",
  measurements: [
    { run_id: "run-a", role: "baseline", metrics: metrics("baseline"), measurement_digest: "m1", captured_at: "2026-10-28T10:01:00Z" },
    { run_id: "run-c", role: "candidate", metrics: metrics("candidate"), measurement_digest: "m2", captured_at: "2026-10-28T10:01:00Z" },
  ],
  evaluation: {
    evaluation_version: "eval-1",
    costs: { baseline: sideCosts(1072, 0), candidate: sideCosts(201, 4) },
    comparisons: [
      row("labour_hours", "Simulated labour time (review + oversight)", "hours", 21.01, 4.75),
      row("false_approval_rate", "False approval rate (of should-reject cases)", "ratio", 0, 0.2, { regression: true, improved: false, relative_change: null }),
    ],
    criteria: [
      { criterion: "equivalent_workloads", label: "The comparison uses equivalent workloads", passed: true, detail: "Identical applications." },
      { criterion: "compliance_thresholds", label: "Compliance thresholds are satisfied", passed: false, detail: "False approvals 20.0% (max 5.0%)." },
    ],
    verdict: "not_successful",
    conclusion: "Not successful — failed criteria: Compliance thresholds are satisfied.",
    limitations: ["All data is synthetic."],
    evaluation_digest: "fedcba9876543210",
    computed_at: "2026-10-28T10:01:00Z",
  },
};

const tool: Partial<AiTool> = {
  id: "tool-1",
  tool_id: "agb-intelligent-kyc-assistant",
  tool_name: "AGB Intelligent KYC Assistant",
  tool_version: "1.0.0",
  status: "active",
  compatible_workflows: ["WF-0001"],
};

const benchmarks: BenchmarkRow[] = [
  {
    tool_id: "agb-intelligent-kyc-assistant",
    tool_version: "1.0.0",
    candidate_mode: "ai_automated",
    experiments: 2,
    successful: 1,
    latest_experiment_id: "exp-1",
    latest_verdict: "not_successful",
    median_relative_change: { labour_hours: -0.774, cost_per_completed_case: -0.697, processing_time_hours: -0.061, accuracy: 0.02 },
  },
];

const routes = {
  ...healthyRoutes,
  "GET /api/v1/experiments": () => jsonResponse(page([experiment])),
  "GET /api/v1/experiments/exp-1": () => jsonResponse(experiment),
  "GET /api/v1/ai-tools": () => jsonResponse(page([tool])),
  "GET /api/v1/benchmarks": () => jsonResponse(benchmarks),
};

describe("Experiments", () => {
  it("shows the verdict, failed criteria, regressions and costs", async () => {
    mockApi(routes);
    renderApp("/experiments");
    expect(await screen.findByRole("heading", { name: /Experiment #3/ })).toBeInTheDocument();
    expect(screen.getAllByText("Not successful").length).toBeGreaterThan(0);
    const criteria = screen.getByRole("list", { name: "Success criteria" });
    expect(within(criteria).getByLabelText("Not met")).toBeInTheDocument();
    expect(within(criteria).getByText("False approvals 20.0% (max 5.0%).")).toBeInTheDocument();
    const comparison = screen.getByRole("table", { name: "Metric comparison" });
    expect(within(comparison).getByRole("row", { name: /False approval rate/ })).toHaveTextContent("Regression");
    const costs = screen.getByRole("table", { name: "Cost breakdown" });
    const rows = within(costs).getAllByRole("row").map((r) => r.textContent ?? "");
    expect(rows[1]).toContain("Review labour"); // fixed reading order
    expect(within(costs).getByRole("row", { name: /AI execution/ })).toHaveTextContent("4.00");
  });

  it("validates a new experiment and sends the stated assumptions", async () => {
    const api = mockApi({ ...routes, "POST /api/v1/experiments": () => jsonResponse({ ...experiment, id: "exp-2", status: "running", evaluation: null }, 202) });
    renderApp("/experiments");
    await userEvent.click(await screen.findByRole("button", { name: "New experiment" }));
    const form = await screen.findByRole("form", { name: "New experiment" });

    const reviewer = within(form).getByLabelText("Reviewer cost per minute");
    await userEvent.clear(reviewer);
    await userEvent.type(reviewer, "-1");
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    expect(within(form).getByText("A number ≥ 0.")).toBeInTheDocument();
    expect(api.requests.some((r) => r.method === "POST")).toBe(false);

    await userEvent.clear(reviewer);
    await userEvent.type(reviewer, "1.1");
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    const body = api.requests.find((r) => r.method === "POST")?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      tool_id: "agb-intelligent-kyc-assistant",
      candidate_mode: "ai_automated",
      applications: 100,
      employees: 25,
      seed: 42,
      costs: { reviewer_cost_per_minute: 1.1, ai_cost_per_invocation: 0.04, currency_label: "USD (illustrative)" },
      thresholds: { max_false_approval_rate: 0.05, max_policy_violations: 0 },
    });
  });

  it("sends the tool version that was chosen, not the newest one", async () => {
    const newer = { ...tool, id: "tool-2", tool_version: "2.0.0" };
    const api = mockApi({
      ...routes,
      "GET /api/v1/ai-tools": () => jsonResponse(page([newer, tool])),
      "POST /api/v1/experiments": () => jsonResponse({ ...experiment, id: "exp-3", status: "running", evaluation: null }, 202),
    });
    renderApp("/experiments");
    await userEvent.click(await screen.findByRole("button", { name: "New experiment" }));
    const form = await screen.findByRole("form", { name: "New experiment" });
    await userEvent.selectOptions(within(form).getByLabelText("AI tool"), "AGB Intelligent KYC Assistant 1.0.0");
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      tool_id: "agb-intelligent-kyc-assistant",
      tool_version: "1.0.0",
    });
  });

  it("runs experiments on the payments scenario with a payment tool", async () => {
    const scenario = (id: string, name: string, workflow: string) => ({
      scenario_id: id,
      version: 1,
      name,
      description: `${name} description`,
      workload: id,
      workflow_id: workflow,
      workflow_version: 1,
      modes: ["baseline", "ai_assisted", "ai_automated"],
      simulated_start: "2026-01-05T09:00:00Z",
      config: {},
    });
    const screener = { ...tool, id: "tool-9", tool_id: "agb-payment-fraud-screener", tool_name: "AGB Payment Fraud Screener", compatible_workflows: ["WF-0002"] };
    const api = mockApi({
      ...routes,
      "GET /api/v1/ai-tools": () => jsonResponse(page([tool, screener])),
      "GET /api/v1/simulations/scenarios": () =>
        jsonResponse([
          scenario("retail-onboarding", "Retail account onboarding", "WF-0001"),
          scenario("domestic-payments", "Domestic payments (fraud screening)", "WF-0002"),
          { ...scenario("personal-loans", "Personal loan origination", "WF-0003"), modes: ["baseline"] },
        ]),
      "POST /api/v1/experiments": () => jsonResponse({ ...experiment, id: "exp-4", status: "running", evaluation: null }, 202),
    });
    renderApp("/experiments");
    await userEvent.click(await screen.findByRole("button", { name: "New experiment" }));
    const form = await screen.findByRole("form", { name: "New experiment" });
    const scenarios = within(form).getByLabelText("Scenario");
    await within(scenarios).findByRole("option", { name: "Domestic payments (fraud screening)" });
    // Only scenarios with AI modes can host an experiment.
    expect(within(scenarios).queryByRole("option", { name: "Personal loan origination" })).not.toBeInTheDocument();
    await userEvent.selectOptions(scenarios, "domestic-payments");
    const tools = within(within(form).getByLabelText("AI tool")).getAllByRole("option").map((o) => o.textContent);
    expect(tools).toEqual(["AGB Payment Fraud Screener 1.0.0"]);
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      scenario_id: "domestic-payments",
      tool_id: "agb-payment-fraud-screener",
    });
  }, 20_000);

  it("lets read-only roles see experiments without starting them", async () => {
    const reader = { ...employeeUser, permissions: [...employeeUser.permissions, "experiments:read" as const] };
    mockApi({ ...routes, ...authRoutes(reader) });
    renderApp("/experiments");
    expect(await screen.findByRole("heading", { name: /Experiment #3/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New experiment" })).not.toBeInTheDocument();
  });
});

describe("Benchmarking", () => {
  it("compares tools and charts baseline against AI with a table view", async () => {
    mockApi(routes);
    renderApp("/benchmarking");
    const leaderboard = await screen.findByRole("table", { name: "Tool benchmarks" });
    expect(await within(leaderboard).findByText("1/2 successful")).toBeInTheDocument();
    expect(within(leaderboard).getByText("-77.4%")).toBeInTheDocument();

    const chart = await screen.findByRole("figure", { name: /Processing time per case/ });
    expect(within(chart).getByText(/A — Baseline \(run #5\)/)).toBeInTheDocument();
    await userEvent.hover(within(chart).getByLabelText("Average, A — Baseline (run #5): 2.81 h"));
    expect(within(chart).getByRole("tooltip")).toHaveTextContent("Average · A — Baseline (run #5): 2.81 h");
    await userEvent.click(within(chart).getByRole("button", { name: "Show table" }));
    const table = within(chart).getByRole("table");
    expect(within(table).getByRole("row", { name: /Average/ })).toHaveTextContent("2.64 h");

    expect(screen.getByRole("figure", { name: /Estimated operating cost/ })).toBeInTheDocument();
    const quality = screen.getByRole("region", { name: "Quality indicators" });
    expect(within(quality).getByText("False approval rate (of should-reject cases)")).toBeInTheDocument();
    expect(within(quality).getByText("Regression")).toBeInTheDocument();
  });
});
