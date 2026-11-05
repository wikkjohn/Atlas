import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { AiTool } from "@/types/aiTools";
import type {
  BenchmarkRow,
  Comparison,
  ExperimentDetail,
  PortfolioDetail,
  PortfolioMetric,
  PortfolioReassessment,
  SeriesDetail,
  SeriesMetric,
  ThresholdOverview,
  ToolComparison,
} from "@/types/experiments";
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

// Phase 80: thresholds per scenario.
const tierThresholds = (fa: number, fr: number) => ({ ...DEFAULT_THRESHOLDS, max_false_approval_rate: fa, max_false_rejection_rate: fr });
const thresholdOverview: ThresholdOverview = {
  tiers: {
    critical: { ...tierThresholds(0.01, 0.1), description: "Financial crime, fraud or sanctions." },
    high: { ...tierThresholds(0.03, 0.08), description: "Credit, market, conduct or reporting risk." },
    medium: { ...DEFAULT_THRESHOLDS, description: "Costly but correctable." },
    low: { ...tierThresholds(0.1, 0.1), description: "Internal, reversible decisions." },
  },
  scenarios: [
    {
      scenario_id: "retail-onboarding",
      name: "Retail account onboarding (AI experiments)",
      workflow_id: "WF-0001",
      risk_tier: "critical",
      default_tier: "critical",
      default_rationale: "Know-your-customer.",
      source: "tier_default",
      version: 0,
      thresholds: tierThresholds(0.01, 0.1),
      rationale: "Know-your-customer.",
      pending: null,
    },
    {
      scenario_id: "leave-requests",
      name: "Leave requests (human resources)",
      workflow_id: "WF-1044",
      risk_tier: "low",
      default_tier: "low",
      default_rationale: "A day off granted in error is easily corrected.",
      source: "scenario",
      version: 1,
      thresholds: tierThresholds(0.1, 0.1),
      rationale: "Approved: leave is reversible.",
      pending: {
        id: "thr-2",
        scenario_id: "leave-requests",
        version: 2,
        risk_tier: "medium",
        thresholds: DEFAULT_THRESHOLDS,
        rationale: "Holiday clashes cost more than we thought.",
        status: "proposed",
        proposed_by_username: "researcher",
        proposed_at: "2026-11-05T09:00:00Z",
        decided_by_username: null,
        decided_at: null,
        decision_note: null,
      },
    },
  ],
};

const reassessment: PortfolioReassessment = {
  portfolio_id: "pf-1",
  stored_cell_verdicts: { successful: 9, not_successful: 48 },
  stored_verdict: "not_successful",
  cell_verdicts: { successful: 6, not_successful: 51 },
  verdict: "not_successful",
  by_tier: { critical: { cells: 12, successful: 3, before: 6 }, low: { cells: 3, successful: 0, before: 0 } },
  cells: [
    { scenario_id: "card-fraud-alerts", country: "GB", risk_tier: "critical", stored_verdict: "successful", verdict: "not_successful", replicates_successful: 2, replicates: 3, failed_criteria: ["compliance_thresholds"] },
  ],
  method: "Each replicate re-evaluated from its stored raw measurements.",
};

// Phase 81: tools compared on matched workloads.
const pairMetric = (metric: string, label: string, a: number, b: number, p: number, finding: "a_better" | "b_better" | "no_significant_difference") => ({
  metric, label, unit: "hours", better: "lower" as const, n: 5, a_mean: a, b_mean: b, mean_difference: a - b,
  relative_difference: (a - b) / b, ci_low: null, ci_high: null, p_value: p, p_adjusted: p, identical: a === b, finding,
});
const toolComparison: ToolComparison = {
  confidence: 0.95,
  method: "Matched workloads, paired t-tests, Holm.",
  benchmarks: [
    {
      scenario_id: "retail-onboarding",
      scenario_version: 2,
      candidate_mode: "ai_assisted",
      risk_tier: "critical",
      tools: [
        { tool: "kyc@1.0.0", tool_id: "kyc", tool_version: "1.0.0", rank: 1, experiments: 5, successful: 5, successful_stored: 5, preferred_in: 1, not_preferred_in: 0, mean_relative_change: { labour_hours: -0.35 } },
        { tool: "kyc@1.1.0", tool_id: "kyc", tool_version: "1.1.0", rank: 1, experiments: 5, successful: 5, successful_stored: 5, preferred_in: 1, not_preferred_in: 0, mean_relative_change: { labour_hours: -0.35 } },
        { tool: "fault@1.0.0", tool_id: "fault", tool_version: "1.0.0", rank: 3, experiments: 5, successful: 0, successful_stored: 0, preferred_in: 0, not_preferred_in: 2, mean_relative_change: { labour_hours: -0.28 } },
      ],
      pairs: [
        { a: "kyc@1.0.0", b: "kyc@1.1.0", matched_workloads: 5, seeds: [81, 82, 83, 84, 85], outcome: "identical", a_better_on: [], b_better_on: [], metrics: [pairMetric("labour_hours", "Simulated labour time", 6, 6, 1, "no_significant_difference")] },
        { a: "fault@1.0.0", b: "kyc@1.0.0", matched_workloads: 5, seeds: [81, 82, 83, 84, 85], outcome: "b_preferred", a_better_on: [], b_better_on: ["labour_hours"], metrics: [pairMetric("labour_hours", "Simulated labour time", 6.85, 6, 0.033, "b_better")] },
      ],
    },
  ],
  scoreboard: [
    { tool: "kyc@1.0.0", tool_id: "kyc", tool_version: "1.0.0", benchmarks: 1, ranked_first: 1, experiments: 5, successful: 5, preferred: 1, not_preferred: 0, trade_off: 0, no_difference: 0, identical: 1, too_few_matched: 0 },
    { tool: "fault@1.0.0", tool_id: "fault", tool_version: "1.0.0", benchmarks: 1, ranked_first: 0, experiments: 5, successful: 0, preferred: 0, not_preferred: 2, trade_off: 0, no_difference: 0, identical: 0, too_few_matched: 0 },
  ],
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/tool-comparison": () => jsonResponse(toolComparison),
  "GET /api/v1/scenario-thresholds": () => jsonResponse(thresholdOverview),
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
    });
    // By default the scenario's thresholds apply, so none are sent.
    expect(body).not.toHaveProperty("thresholds");
  });

  it("shows the scenario's thresholds, or sends the experiment's own", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/experiments": () => jsonResponse({ ...experiment, id: "exp-4", status: "running", evaluation: null }, 202),
    });
    renderApp("/experiments");
    await userEvent.click(await screen.findByRole("button", { name: "New experiment" }));
    const form = await screen.findByRole("form", { name: "New experiment" });
    expect(await within(form).findByLabelText("Scenario thresholds in force")).toHaveTextContent("Critical risk");
    expect(within(form).getByLabelText("Scenario thresholds in force")).toHaveTextContent("False approvals ≤ 1.0%");
    await userEvent.click(within(form).getByLabelText("Use the scenario's thresholds"));
    // Starting from the scenario's values.
    const falseApprovals = within(form).getByLabelText("Maximum false approval rate");
    expect(falseApprovals).toHaveValue(0.01);
    await userEvent.clear(falseApprovals);
    await userEvent.type(falseApprovals, "0.02");
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      thresholds: { max_false_approval_rate: 0.02, max_false_rejection_rate: 0.1 },
    });
   });

  it("lists thresholds by scenario, proposes new ones and decides another's proposal", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/scenario-thresholds": () => jsonResponse({ ...thresholdOverview.scenarios[1].pending, id: "thr-3" }, 201),
      "POST /api/v1/scenario-thresholds/thr-2/approve": () => jsonResponse({ ...thresholdOverview.scenarios[1].pending, status: "active" }),
    });
    renderApp("/experiments");
    const table = await screen.findByRole("table", { name: "Thresholds by scenario" });
    const onboarding = within(table).getByRole("row", { name: /Retail account onboarding/ });
    expect(onboarding).toHaveTextContent("Critical");
    expect(onboarding).toHaveTextContent("Tier default");
    const leave = within(table).getByRole("row", { name: /Leave requests/ });
    expect(leave).toHaveTextContent("Approved v1");
    expect(leave).toHaveTextContent("v2 (medium) proposed by researcher");
    await userEvent.click(within(leave).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/v1/scenario-thresholds/thr-2/approve")).toBe(true));

    await userEvent.click(within(onboarding).getByRole("button", { name: "Propose" }));
    const form = await screen.findByRole("form", { name: "Propose thresholds" });
    await userEvent.selectOptions(within(form).getByLabelText("Risk tier"), "high");
    expect(within(form).getByLabelText("Maximum false approval rate")).toHaveValue(0.03);
    await userEvent.click(screen.getByRole("button", { name: "Submit proposal" }));
    expect(within(form).getByText("Say why, in at least 20 characters.")).toBeInTheDocument();
    await userEvent.type(within(form).getByLabelText("Rationale"), "Onboarding errors are caught by later monitoring.");
    await userEvent.click(screen.getByRole("button", { name: "Submit proposal" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST" && r.path === "/api/v1/scenario-thresholds")).toBe(true));
    expect(api.requests.find((r) => r.path === "/api/v1/scenario-thresholds" && r.method === "POST")?.body).toMatchObject({
      scenario_id: "retail-onboarding",
      risk_tier: "high",
      thresholds: { max_false_approval_rate: 0.03, max_false_rejection_rate: 0.08 },
    });
  });

  it("re-judges a portfolio's cells by each scenario's thresholds", async () => {
    const api = mockApi({ ...routes, "GET /api/v1/experiment-portfolios/pf-1/under-scenario-thresholds": () => jsonResponse(reassessment) });
    renderApp("/experiments");
    const section = await screen.findByRole("region", { name: "Under scenario thresholds" });
    await userEvent.click(within(section).getByRole("button", { name: "Judge each cell by its scenario's thresholds" }));
    expect(await within(section).findByText(/6 of 1 cells successful \(stored: 9\)/)).toBeInTheDocument();
    const tiers = within(section).getByRole("table", { name: "Cells by risk tier" });
    expect(within(tiers).getByRole("row", { name: /Critical/ })).toHaveTextContent("1236");
    expect(within(section).getByText(/card-fraud-alerts \(GB\) → Not successful/)).toBeInTheDocument();
    expect(api.requests.some((r) => r.path.endsWith("/under-scenario-thresholds"))).toBe(true);
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

  it("ranks tools on matched workloads and shows each head-to-head", async () => {
    mockApi(routes);
    renderApp("/benchmarking");
    const board = await screen.findByRole("table", { name: "Scoreboard across benchmarks" });
    expect(within(board).getByRole("row", { name: /fault@1.0.0/ })).toHaveTextContent("0 / 2");
    const ranking = screen.getByRole("table", { name: "Ranking on retail-onboarding" });
    // Tools nothing separates share a rank.
    expect(within(ranking).getAllByText("#1")).toHaveLength(2);
    expect(within(ranking).getByRole("row", { name: /fault@1.0.0/ })).toHaveTextContent("#3");
    const benchmark = screen.getByRole("region", { name: "Benchmark retail-onboarding" });
    expect(within(benchmark).getByText("Identical results")).toBeInTheDocument();
    expect(within(benchmark).getByText("kyc@1.0.0 preferred")).toBeInTheDocument();
    const pair = within(benchmark).getByRole("table", { name: "fault@1.0.0 against kyc@1.0.0" });
    expect(within(pair).getByRole("row", { name: /Simulated labour time/ })).toHaveTextContent("B better");
    expect(within(pair).getByRole("row", { name: /Simulated labour time/ })).toHaveTextContent("+14.2%");
  });

  it("starts a comparison of several tools on the same seeds", async () => {
    const fault = { ...tool, id: "tool-9", tool_id: "kyc-fault-injector", tool_name: "KYC Fault Injector" };
    const api = mockApi({
      ...routes,
      "GET /api/v1/ai-tools": () => jsonResponse(page([tool, fault])),
      "POST /api/v1/tool-comparison/runs": () => jsonResponse({ series: [series, series] }, 202),
    });
    renderApp("/benchmarking");
    await userEvent.click(await screen.findByRole("button", { name: "Compare tools" }));
    const form = await screen.findByRole("form", { name: "Compare tools" });
    await userEvent.click(within(form).getByLabelText(/AGB Intelligent KYC Assistant/));
    await userEvent.click(screen.getByRole("button", { name: "Start comparison" }));
    expect(within(form).getByText("Choose 2 to 5 tools.")).toBeInTheDocument();
    await userEvent.click(within(form).getByLabelText(/KYC Fault Injector/));
    await userEvent.click(screen.getByRole("button", { name: "Start comparison" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      scenario_id: "retail-onboarding",
      tools: [
        { tool_id: "agb-intelligent-kyc-assistant", tool_version: "1.0.0" },
        { tool_id: "kyc-fault-injector", tool_version: "1.0.0" },
      ],
      candidate_mode: "ai_assisted",
      replicates: 3,
    });
  });
});
