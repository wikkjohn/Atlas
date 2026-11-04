import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { AiTool } from "@/types/aiTools";
import type { BenchmarkRow, Comparison, ExperimentDetail, PortfolioDetail, PortfolioMetric, SeriesDetail, SeriesMetric } from "@/types/experiments";
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

// A repeated-seed series (Phase 77): labour clearly down, accuracy within noise.
const seriesMetric = (metric: string, label: string, rel: number, low: number, high: number, p: number, finding: SeriesMetric["finding"]): SeriesMetric => ({
  metric,
  label,
  unit: "hours",
  better: metric === "accuracy" ? "higher" : "lower",
  n: 5,
  baseline_mean: 47.07,
  candidate_mean: 47.07 * (1 + rel),
  mean_delta: 47.07 * rel,
  ci_low: 47.07 * low,
  ci_high: 47.07 * high,
  relative_change: rel,
  relative_ci_low: low,
  relative_ci_high: high,
  p_value: p,
  p_adjusted: p,
  significant: finding === "improved" || finding === "worse",
  finding,
  per_seed: [],
});
const series: SeriesDetail = {
  id: "ser-1",
  series_number: 2,
  name: "KYC assistant over five seeds",
  scenario_id: "retail-onboarding",
  scenario_version: 2,
  candidate_mode: "ai_assisted",
  tool_id: "agb-intelligent-kyc-assistant",
  tool_version: "1.0.0",
  seeds: [101, 102, 103, 104, 105],
  confidence: 0.95,
  status: "completed",
  failure_reason: null,
  verdict: "successful",
  replicates_completed: 5,
  created_by_username: "researcher",
  created_at: "2026-11-04T04:00:00Z",
  completed_at: "2026-11-04T04:05:00Z",
  configuration: {},
  experiments: [],
  statistics: {
    method: "paired t-test on per-seed differences",
    confidence: 0.95,
    replicates: 5,
    seeds: [101, 102, 103, 104, 105],
    replicate_verdicts: { successful: 5, not_successful: 0 },
    metrics: [
      seriesMetric("labour_hours", "Simulated labour time (review + oversight)", -0.344, -0.357, -0.331, 0.0000029, "improved"),
      seriesMetric("accuracy", "Decisions matching ground truth", 0.026, 0.007, 0.046, 0.163, "no_significant_difference"),
    ],
    significantly_worse: [],
    verdict: "successful",
    conclusion: "Over 5 seeds: labour time down 34.4%.",
  },
};

// A portfolio (Phase 78): the review assistants across workflows, departments and countries.
const portfolioMetric = (metric: string, label: string, mean: number, low: number, high: number, p: number, finding: PortfolioMetric["finding"], better: [number, number, number]): PortfolioMetric => ({
  metric,
  label,
  better: metric === "accuracy" ? "higher" : "lower",
  workflows: 19,
  cells: 57,
  country_dependent_workflows: 0,
  mean_relative_change: mean,
  ci_low: low,
  ci_high: high,
  median_relative_change: mean,
  p_value: p,
  p_adjusted: p,
  significant: finding === "improved" || finding === "worse",
  finding,
  cell_findings: { improved: better[0], worse: better[1], no_significant_difference: better[2] },
  by_department: [
    { department: "Cards", cells: 3, mean_relative_change: -0.41 },
    { department: "Human Resources", cells: 3, mean_relative_change: -0.12 },
  ],
  by_country: [
    { country: "GB", cells: 19, mean_relative_change: -0.3 },
    { country: "JP", cells: 19, mean_relative_change: -0.29 },
  ],
});
const portfolio: PortfolioDetail = {
  id: "pf-1",
  portfolio_number: 1,
  name: "AGB review assistants",
  family: "agb-review-assistants",
  candidate_mode: "ai_assisted",
  countries: ["GB", "US", "JP"],
  seeds: [301, 302, 303],
  applications: 40,
  employees: 20,
  confidence: 0.95,
  status: "completed",
  failure_reason: null,
  verdict: "not_successful",
  cells: 57,
  cells_completed: 57,
  created_by_username: "researcher",
  created_at: "2026-11-04T19:00:00Z",
  completed_at: "2026-11-04T19:40:00Z",
  configuration: { plan: { cells: [], skipped: [{ scenario_id: "domestic-payments-outage", reason: "an outage scenario: its effects come from the outage" }] } },
  series: [],
  statistics: {
    method: "the cell is the unit",
    confidence: 0.95,
    cells: 57,
    workflows: 19,
    departments: ["Cards", "Human Resources"],
    countries: ["GB", "JP", "US"],
    tools: ["agb-card-fraud-assistant"],
    cell_verdicts: { successful: 50, not_successful: 7 },
    cells_with_a_worse_metric: ["leave-requests (GB)"],
    metrics: [
      portfolioMetric("labour_hours", "Simulated labour time (review + oversight)", -0.3, -0.34, -0.26, 0.0000001, "improved", [55, 0, 2]),
      portfolioMetric("accuracy", "Decisions matching ground truth", 0.004, -0.002, 0.01, 0.4, "no_significant_difference", [5, 1, 51]),
    ],
    cell_summaries: [],
    verdict: "not_successful",
    conclusion: "Across 57 cells (19 workflows, 18 departments, 3 countries), mean change per cell: labour time -30.0%.",
  },
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/experiment-portfolios": () => jsonResponse(page([portfolio])),
  "GET /api/v1/experiment-portfolios/pf-1": () => jsonResponse(portfolio),
  "GET /api/v1/experiment-series": () => jsonResponse(page([series])),
  "GET /api/v1/experiment-series/ser-1": () => jsonResponse(series),
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

describe("Repeated-seed series", () => {
  it("shows the effect across seeds with its interval and adjusted p-value", async () => {
    mockApi(routes);
    renderApp("/experiments");
    const details = await screen.findByRole("region", { name: "Series details" });
    expect(within(details).getByText(/seeds 101, 102, 103, 104, 105 · 5 of 5 replicates evaluated/)).toBeInTheDocument();
    expect(within(details).getByText("Over 5 seeds: labour time down 34.4%.")).toBeInTheDocument();
    const table = within(details).getByRole("table", { name: "Effect across seeds" });
    const labour = within(table).getByRole("row", { name: /Simulated labour time/ });
    expect(labour).toHaveTextContent("-34.4%");
    expect(labour).toHaveTextContent("-35.7% to -33.1%");
    expect(labour).toHaveTextContent("< 0.001");
    expect(labour).toHaveTextContent("Better");
    // An interval that excludes zero, but not significant once adjusted for many metrics.
    const accuracy = within(table).getByRole("row", { name: /Decisions matching ground truth/ });
    expect(accuracy).toHaveTextContent("+0.7% to +4.6%");
    expect(accuracy).toHaveTextContent("0.163");
    expect(accuracy).toHaveTextContent("No significant difference");
  });

  it("starts a series over several seeds", async () => {
    const api = mockApi({ ...routes, "POST /api/v1/experiment-series": () => jsonResponse({ ...series, id: "ser-2", status: "running", statistics: null, verdict: null }, 202) });
    renderApp("/experiments");
    await userEvent.click(await screen.findByRole("button", { name: "New series" }));
    const form = await screen.findByRole("form", { name: "New series" });
    const seeds = within(form).getByLabelText("Seeds");
    await userEvent.clear(seeds);
    await userEvent.type(seeds, "1");
    await userEvent.click(screen.getByRole("button", { name: "Run series" }));
    expect(within(form).getByText("2 – 30 seeds.")).toBeInTheDocument();
    expect(api.requests.some((r) => r.method === "POST")).toBe(false);
    await userEvent.clear(seeds);
    await userEvent.type(seeds, "8");
    await userEvent.click(screen.getByRole("button", { name: "Run series" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      tool_id: "agb-intelligent-kyc-assistant",
      tool_version: "1.0.0",
      candidate_mode: "ai_assisted",
      seed: 101,
      replicates: 8,
      confidence: 0.95,
    });
  });
});

describe("Portfolios", () => {
  it("pools the cells and breaks them down by department and country", async () => {
    mockApi(routes);
    renderApp("/experiments");
    const details = await screen.findByRole("region", { name: "Portfolio details" });
    expect(within(details).getByText(/countries GB, US, JP · 3 seeds per cell · 57 of 57 cells evaluated · 19 workflows, 2 departments/)).toBeInTheDocument();
    const table = within(details).getByRole("table", { name: "Effect across cells" });
    const labour = within(table).getByRole("row", { name: /Simulated labour time/ });
    expect(labour).toHaveTextContent("-30.0%");
    expect(labour).toHaveTextContent("-34.0% to -26.0%");
    expect(labour).toHaveTextContent("55 / 0 / 2");
    expect(labour).toHaveTextContent("Better");
    const departments = within(details).getByRole("table", { name: "By department" });
    expect(within(departments).getByRole("row", { name: /Human Resources/ })).toHaveTextContent("-12.0%");
    expect(within(details).getByRole("table", { name: "By country" })).toHaveTextContent("JP");
    await userEvent.selectOptions(within(details).getByLabelText("Breakdown of"), "Decisions matching ground truth");
    expect(within(details).getByText("1 scenario(s) not in the portfolio")).toBeInTheDocument();
  });

  it("starts a portfolio for a tool family in several countries", async () => {
    const api = mockApi({ ...routes, "POST /api/v1/experiment-portfolios": () => jsonResponse({ ...portfolio, id: "pf-2", status: "running", statistics: null, verdict: null }, 202) });
    renderApp("/experiments");
    await userEvent.click(await screen.findByRole("button", { name: "New portfolio" }));
    const form = await screen.findByRole("form", { name: "New portfolio" });
    const countries = within(form).getByLabelText("Countries");
    await userEvent.clear(countries);
    await userEvent.type(countries, "GB, GB");
    await userEvent.click(screen.getByRole("button", { name: "Run portfolio" }));
    expect(within(form).getByText("1 – 10 different country codes, e.g. GB, US.")).toBeInTheDocument();
    expect(api.requests.some((r) => r.method === "POST")).toBe(false);
    await userEvent.clear(countries);
    await userEvent.type(countries, "gb, sg");
    await userEvent.click(screen.getByRole("button", { name: "Run portfolio" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      family: "agb-review-assistants",
      candidate_mode: "ai_assisted",
      countries: ["GB", "SG"],
      replicates: 3,
    });
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
