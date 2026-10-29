import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { AiAction, AiAdapter, AiTool, Invocation } from "@/types/aiTools";
import type { Scenario, SimulationRunDetail } from "@/types/simulations";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const tool: AiTool = {
  id: "tool-1",
  tool_id: "agb-intelligent-kyc-assistant",
  tool_name: "AGB Intelligent KYC Assistant",
  tool_version: "1.0.0",
  provider: "ATLAS Global Bank",
  description: "Analyses synthetic retail applications.",
  adapter: "rule_based_kyc",
  input_schema: { type: "object" },
  output_schema: { type: "object" },
  allowed_actions: ["analyze_application", "recommend_decision"],
  permissions: ["customers:read"],
  compatible_workflows: ["WF-0001"],
  configuration: { timeout_seconds: 5 },
  status: "active",
  created_by_username: null,
  created_at: "2026-10-28T09:00:00Z",
  invocations: 3,
  failures: 1,
};

const adapters: AiAdapter[] = [
  {
    key: "rule_based_kyc",
    name: "Rule-based KYC analysis",
    provider: "ATLAS",
    description: "Deterministic rules.",
    supported_actions: ["analyze_application", "complete_low_risk_review", "recommend_decision"],
    input_schema: {},
    output_schema: {},
    configuration_schema: {},
  },
];

const actions: AiAction[] = [
  { action: "analyze_application", grantable: true, description: "Analyse." },
  { action: "recommend_decision", grantable: true, description: "Recommend." },
  { action: "complete_low_risk_review", grantable: true, description: "Low-risk review." },
  { action: "approve_account", grantable: false, description: "Never delegated." },
];

const scenarioV2: Scenario = {
  scenario_id: "retail-onboarding",
  version: 2,
  name: "Retail account onboarding (AI experiments)",
  description: "",
  workload: "retail_onboarding",
  workflow_id: "WF-0001",
  workflow_version: 2,
  modes: ["baseline", "ai_assisted", "ai_automated"],
  simulated_start: "2026-01-05T09:00:00Z",
  config: {},
};

const invocation = (partial: Partial<Invocation>): Invocation => ({
  id: "inv-1",
  tool_record_id: "tool-1",
  tool_id: tool.tool_id,
  tool_version: "1.0.0",
  action: "recommend_decision",
  status: "succeeded",
  input: {},
  output: { recommendation: "approve", risk_classification: "low", explanation: "Recommend approve (low risk)." },
  error: null,
  duration_ms: 2,
  usage: {},
  invoked_by: "user-1",
  execution_id: null,
  simulation_run_id: null,
  occurred_at: "2026-10-28T09:00:00Z",
  created_at: "2026-10-28T09:00:00Z",
  ...partial,
});

const run = (id: string, n: number, mode: SimulationRunDetail["mode"], accuracy: number): SimulationRunDetail => ({
  id,
  run_number: n,
  scenario_id: "retail-onboarding",
  scenario_version: 2,
  workflow_id: "WF-0001",
  workflow_version: 2,
  profile: "custom",
  seed: 42,
  applications: 100,
  employees: 25,
  status: "completed",
  failure_reason: null,
  software_version: "0.6.0",
  config_hash: "abc",
  result_digest: "def",
  created_by_username: "researcher",
  created_at: "2026-10-28T09:00:00Z",
  started_at: null,
  completed_at: null,
  wall_ms: 1000,
  progress: {},
  percent_complete: 100,
  mode,
  tool_id: mode === "baseline" ? null : tool.tool_id,
  tool_version: mode === "baseline" ? null : "1.0.0",
  batch_id: "batch-1",
  config: {},
  results: {
    cases: 100,
    completed: 100,
    unfinished: 0,
    outcomes: { approved: 87, rejected: 13 },
    by_kind: {},
    risk_ratings: {},
    ground_truth: { correct: 98, false_approvals: 0, false_rejections: 2, accuracy },
    manual_reviews: mode === "ai_automated" ? 12 : 92,
    straight_through_rate: 0.08,
    review_labor_hours: mode === "baseline" ? 21 : 13,
    overdue_tasks: 0,
    cycle_time_hours: {},
    review_queue_wait_hours: {},
    staff: {},
    simulated_hours: 80,
    ai: {
      mode: "x",
      invocations: 96,
      invocation_statuses: { succeeded: 96 },
      failed_invocations: 0,
      recommendations: {},
      escalations: 4,
      recommendation_accuracy: 1,
      automated_approvals: mode === "ai_automated" ? 80 : 0,
    },
    execution: { events_processed: 1, workflow_steps_completed: 1, wall_ms: 1, cases_per_second: 1 },
  },
  simulated_start: "2026-01-05T09:00:00Z",
  simulated_end: null,
  staff_unit_id: null,
  reproductions: [],
  history_state: "present",
  archive: null,
});

const routes = {
  ...healthyRoutes,
  "GET /api/v1/ai-tools": () => jsonResponse(page([tool])),
  "GET /api/v1/ai-tools/tool-1": () => jsonResponse(tool),
  "GET /api/v1/ai-tools/adapters": () => jsonResponse(adapters),
  "GET /api/v1/ai-tools/actions": () => jsonResponse(actions),
  "GET /api/v1/ai-tools/invocations": () => jsonResponse(page([invocation({ status: "blocked", output: null, error: { message: "Not permitted" } })])),
  "GET /api/v1/simulations/scenarios": () => jsonResponse([scenarioV2]),
  "GET /api/v1/workflows": () => jsonResponse([{ workflow_id: "WF-0001", name: "Retail Account Opening", version: 2, versions: [1, 2], description: "", business_owner: "", trigger_type: "api", step_count: 21 }]),
};

describe("AI Innovation Lab", () => {
  it("shows the registry, capabilities and recorded invocations", async () => {
    mockApi(routes);
    renderApp("/ai-lab");
    expect(await screen.findByRole("heading", { name: "AGB Intelligent KYC Assistant" })).toBeInTheDocument();
    const capabilities = screen.getByRole("region", { name: "Capabilities" });
    expect(within(capabilities).getByText("recommend_decision")).toBeInTheDocument();
    expect(within(capabilities).getByText(/cannot approve accounts/)).toBeInTheDocument();
    const invocations = await screen.findByRole("table", { name: "Invocations" });
    expect(within(invocations).getByText("Blocked")).toBeInTheDocument();
    expect(within(invocations).getByText("Not permitted")).toBeInTheDocument();
  });

  it("validates a registration and never offers forbidden actions", async () => {
    const api = mockApi({ ...routes, "POST /api/v1/ai-tools": () => jsonResponse({ ...tool, id: "tool-2" }, 201) });
    renderApp("/ai-lab");
    await userEvent.click(await screen.findByRole("button", { name: "Register a tool" }));
    const form = await screen.findByRole("form", { name: "Register an AI tool" });

    expect(await within(form).findByRole("checkbox", { name: /approve_account/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Register tool" }));
    expect(within(form).getByText("Lower-case letters, digits and single hyphens.")).toBeInTheDocument();
    expect(api.requests.some((r) => r.method === "POST")).toBe(false);

    await userEvent.type(within(form).getByLabelText("Tool ID"), "kyc-model-b");
    await userEvent.type(within(form).getByLabelText("Name"), "KYC Model B");
    await userEvent.type(within(form).getByLabelText("Provider"), "Example Vendor");
    await userEvent.click(screen.getByRole("button", { name: "Register tool" }));
    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toMatchObject({
      tool_id: "kyc-model-b",
      tool_version: "1.0.0",
      adapter: "rule_based_kyc",
      allowed_actions: ["analyze_application", "recommend_decision"],
      compatible_workflows: ["WF-0001"],
      configuration: {},
    });
  });

  it("invokes a tool from the test console and shows its explanation", async () => {
    const api = mockApi({ ...routes, "POST /api/v1/ai-tools/tool-1/invoke": () => jsonResponse(invocation({})) });
    renderApp("/ai-lab?tool=tool-1");
    const console = await screen.findByRole("form", { name: "Test console" });
    await userEvent.click(within(console).getByRole("button", { name: "Invoke" }));
    const result = await within(console).findByRole("status");
    expect(result).toHaveTextContent("Recommendation: Approve");
    expect(result).toHaveTextContent("Recommend approve (low risk).");
    const body = api.requests.find((r) => r.method === "POST")?.body as { action: string; input: { application: unknown } };
    expect(body.action).toBe("analyze_application");
    expect(body.input.application).toBeDefined();
  });

  it("offers the underwriting assistant a referred loan application", async () => {
    const underwriter: AiTool = {
      ...tool,
      id: "tool-3",
      tool_id: "agb-credit-underwriting-assistant",
      tool_name: "AGB Credit Underwriting Assistant",
      adapter: "rule_based_credit_underwriting",
      allowed_actions: ["analyze_credit_application", "recommend_decision", "complete_low_risk_review"],
      compatible_workflows: ["WF-0003"],
    };
    const api = mockApi({
      ...routes,
      "GET /api/v1/ai-tools": () => jsonResponse(page([underwriter])),
      "GET /api/v1/ai-tools/tool-3": () => jsonResponse(underwriter),
      "POST /api/v1/ai-tools/tool-3/invoke": () => jsonResponse(invocation({})),
    });
    renderApp("/ai-lab?tool=tool-3");
    const console = await screen.findByRole("form", { name: "Test console" });
    expect(within(console).getByLabelText("Action")).toHaveValue("analyze_credit_application");
    await userEvent.click(within(console).getByRole("button", { name: "Invoke" }));
    await within(console).findByRole("status");
    const body = api.requests.find((r) => r.method === "POST")?.body as {
      action: string;
      input: { income: { declared_to_estimate: number } };
    };
    expect(body.action).toBe("analyze_credit_application");
    expect(body.input.income.declared_to_estimate).toBe(2);
  });

  it("starts an A/B/C experiment on one seed and compares the runs", async () => {
    const runs = [run("r1", 1, "baseline", 0.98), run("r2", 2, "ai_assisted", 1), run("r3", 3, "ai_automated", 1)];
    const api = mockApi({
      ...routes,
      "POST /api/v1/simulations/suites": () => jsonResponse(runs, 202),
      "GET /api/v1/simulations": () => jsonResponse(page(runs)),
      "GET /api/v1/simulations/r1": () => jsonResponse(runs[0]),
      "GET /api/v1/simulations/r2": () => jsonResponse(runs[1]),
      "GET /api/v1/simulations/r3": () => jsonResponse(runs[2]),
    });
    renderApp("/ai-lab?tool=tool-1");
    const form = await screen.findByRole("form", { name: "Configure an experiment" });
    await userEvent.click(within(form).getByRole("button", { name: "Start test runs" }));

    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/v1/simulations/suites")).toBe(true));
    expect(api.requests.find((r) => r.path === "/api/v1/simulations/suites")?.body).toEqual({
      scenario_id: "retail-onboarding",
      scenario_version: 2,
      profile: "custom",
      applications: 100,
      employees: 25,
      seed: 42,
      modes: ["baseline", "ai_assisted", "ai_automated"],
      tool_id: "agb-intelligent-kyc-assistant",
      tool_version: "1.0.0",
    });
    const table = await screen.findByRole("table", { name: "Experiment runs" });
    const automated = await within(table).findByRole("row", { name: /C — AI automated tasks/ });
    await waitFor(() => expect(automated).toHaveTextContent("80"));
    expect(within(table).getByRole("row", { name: /A — Baseline/ })).toHaveTextContent("98.0%");
  });

  it("gives read-only roles the registry without management, testing or experiments", async () => {
    const reader = { ...employeeUser, permissions: [...employeeUser.permissions, "ai_tools:read" as const] };
    mockApi({ ...routes, ...authRoutes(reader) });
    renderApp("/ai-lab");
    expect(await screen.findByRole("heading", { name: "AGB Intelligent KYC Assistant" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register a tool" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Test console" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Configure an experiment" })).not.toBeInTheDocument();
  });
});
