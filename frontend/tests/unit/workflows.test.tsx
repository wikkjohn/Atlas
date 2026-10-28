import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { syntheticDocumentNumber } from "@/services/workflows";
import type { ExecutionDetail, WorkflowDefinition, WorkflowMetrics, WorkflowTask } from "@/types/workflows";

import { germany } from "./enterprise-fixtures";
import { healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const definition: WorkflowDefinition = {
  workflow_id: "WF-0001",
  name: "Retail Account Opening",
  version: 1,
  versions: [1],
  description: "Onboards a synthetic retail customer.",
  business_owner: "Retail Banking",
  trigger_type: "api",
  step_count: 3,
  start: "receive_application",
  input_schema: {},
  steps: [
    { id: "receive_application", type: "service_task", name: "Customer submits application", next: "account_approval" },
    {
      id: "account_approval",
      type: "approval",
      name: "Authorized approval",
      approval: { permissions: ["accounts:approve"], distinct_from: ["initiator"] },
      transitions: [{ to: "complete" }],
    },
    { id: "complete", type: "completion", name: "Case closed" },
  ],
  transition_rules: [],
  approval_policies: [],
  failure_policies: [],
  timeout_policies: [],
};

const metrics: WorkflowMetrics = {
  workflow_id: "WF-0001",
  executions: { completed: 4, waiting: 1 },
  outcomes: { approved: 3, rejected: 1 },
  avg_execution_ms: 7_200_000,
  bottleneck_step: "account_approval",
  steps: [
    { step_id: "account_approval", step_name: "Authorized approval", step_type: "approval", runs: 5, completed: 4, failed: 0, open: 1, retries: 0, avg_ms: 3_600_000, p50_ms: 3_000_000, p95_ms: 7_000_000, max_ms: 7_200_000 },
  ],
};

const task = (partial: Partial<WorkflowTask>): WorkflowTask => ({
  run_id: "run-1",
  execution_id: "exe-1",
  workflow_id: "WF-0001",
  step_id: "account_approval",
  step_name: "Authorized approval",
  step_type: "approval",
  opened_at: "2026-10-27T10:00:00Z",
  due_at: null,
  overdue: false,
  required_permissions: ["accounts:approve"],
  can_act: true,
  blocked_reason: null,
  subject: "Grace Hopper",
  risk_rating: "low",
  flags: [],
  initiated_by_username: "employee",
  ...partial,
});

const failedExecution: ExecutionDetail = {
  id: "exe-9",
  workflow_id: "WF-0001",
  workflow_version: 1,
  status: "failed",
  outcome: "failed",
  current_steps: [],
  business_key: null,
  subject: "Ada Lovelace",
  initiated_by: "u1",
  initiated_by_username: "employee",
  correlation_id: null,
  started_at: "2026-10-27T10:00:00Z",
  completed_at: "2026-10-27T10:00:01Z",
  duration_ms: 1000,
  context: { input: { applicant_name: "Ada Lovelace" } },
  error: { step: "open_account", code: "business_rule_violation", message: "The customer is no longer eligible" },
  steps: [
    {
      id: "r1", sequence: 1, step_id: "open_account", step_name: "Create the customer account", step_type: "service_task",
      status: "failed", branch: null, attempt: 1, required_permissions: [], actor_id: null, actor_username: null,
      output: null, error: { code: "business_rule_violation", message: "The customer is no longer eligible" },
      created_at: "2026-10-27T10:00:00Z", started_at: "2026-10-27T10:00:00Z", completed_at: "2026-10-27T10:00:01Z",
      duration_ms: 12, not_before: null, due_at: null, escalated_at: null,
    },
  ],
};

function routes(extra = {}) {
  return {
    ...healthyRoutes,
    "GET /api/v1/workflows": () => jsonResponse([definition]),
    "GET /api/v1/workflows/WF-0001": () => jsonResponse(definition),
    "GET /api/v1/workflows/WF-0001/metrics": () => jsonResponse(metrics),
    "GET /api/v1/countries": () => jsonResponse(page([germany])),
    ...extra,
  };
}

describe("Workflow Explorer", () => {
  it("shows the definition, its policies and the measured bottleneck", async () => {
    mockApi(routes());
    renderApp("/workflows");

    const table = await screen.findByRole("table", { name: "Process steps" });
    const approval = within(table).getByText("Authorized approval").closest("tr") as HTMLElement;
    expect(within(approval).getByText("Bottleneck")).toBeInTheDocument();
    expect(within(approval).getByText("Needs accounts:approve; not initiator")).toBeInTheDocument();
    expect(within(approval).getByText("1.9 h")).toBeInTheDocument(); // p95 of 7,000,000 ms
    expect(screen.getByText("2.0 h")).toBeInTheDocument(); // average execution
  });

  it("generates synthetic document numbers with valid check digits", () => {
    for (let i = 0; i < 20; i++) {
      const n = syntheticDocumentNumber("passport");
      expect(n).toMatch(/^P\d{8}$/);
      const digits = n.slice(1, 8).split("").map(Number);
      expect(digits.reduce((a, b) => a + b, 0) % 10).toBe(Number(n[8]));
    }
  });

  it("starts an application with an idempotency key", async () => {
    const api = mockApi(
      routes({
        "POST /api/v1/workflows/WF-0001/executions": () => jsonResponse({ ...failedExecution, id: "new-1", status: "waiting", outcome: null, error: null, steps: [] }, 201),
        "GET /api/v1/workflow-executions": () => jsonResponse(page([])),
        "GET /api/v1/workflow-executions/new-1": () => jsonResponse({ ...failedExecution, id: "new-1", status: "waiting", outcome: null, error: null, steps: [] }),
        "GET /api/v1/workflow-executions/new-1/history": () => jsonResponse([]),
      }),
    );
    renderApp("/workflows");

    await userEvent.click(await screen.findByRole("button", { name: "Start an application" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Applicant name"), "Grace Hopper");
    await userEvent.type(within(dialog).getByLabelText("Date of birth"), "1986-12-09");
    await userEvent.selectOptions(within(dialog).getByLabelText("Country"), await within(dialog).findByRole("option", { name: "Germany" }));
    await userEvent.click(within(dialog).getByLabelText("Proof of address (synthetic)"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit application" }));

    await screen.findByRole("dialog", { name: "Workflow execution" });
    const post = api.requests.find((r) => r.method === "POST");
    const input = (post?.body as { input: { documents: { document_type: string }[]; applicant_name: string } }).input;
    expect(input.applicant_name).toBe("Grace Hopper");
    expect((input as unknown as { country_code: string }).country_code).toBe("DE");
    expect(input.documents.map((d) => d.document_type)).toEqual(["passport"]);
    expect(post?.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("lets permitted users decide tasks and explains blocked ones", async () => {
    const api = mockApi(
      routes({
        "GET /api/v1/workflow-tasks": () =>
          jsonResponse(page([task({}), task({ run_id: "run-2", subject: "Own Case", can_act: false, blocked_reason: "Four-eyes rule: the person who started this case cannot decide it." })])),
        "POST /api/v1/workflow-tasks/run-1/complete": () => jsonResponse(failedExecution),
      }),
    );
    renderApp("/workflows?tab=tasks");

    const tasks = await screen.findByRole("list", { name: "Tasks" });
    const own = (await within(tasks).findByText(/Own Case/)).closest("li") as HTMLElement;
    expect(within(own).getByText(/Four-eyes rule/)).toBeInTheDocument();
    expect(within(own).queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();

    const mine = within(tasks).getByText(/Grace Hopper/).closest("li") as HTMLElement;
    await userEvent.type(within(mine).getByLabelText("Note for Grace Hopper"), "Docs verified");
    await userEvent.click(within(mine).getByRole("button", { name: /Approve/ }));

    await waitFor(() => expect(api.requests.some((r) => r.method === "POST")).toBe(true));
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({ decision: "approve", note: "Docs verified" });
  });

  it("shows where and why an execution failed", async () => {
    mockApi(
      routes({
        "GET /api/v1/workflow-executions": () => jsonResponse(page([])),
        "GET /api/v1/workflow-executions/exe-9": () => jsonResponse(failedExecution),
        "GET /api/v1/workflow-executions/exe-9/history": () => jsonResponse([]),
      }),
    );
    renderApp("/workflows?tab=executions&execution=exe-9");

    const dialog = await screen.findByRole("dialog", { name: "Workflow execution" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Failed at open_account: The customer is no longer eligible");
    expect(within(dialog).getByText("business_rule_violation: The customer is no longer eligible")).toBeInTheDocument();
  });
});
