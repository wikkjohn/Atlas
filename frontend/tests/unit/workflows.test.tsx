import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { syntheticDocumentNumber } from "@/services/workflows";
import type { ExecutionDetail, WorkflowDefinition, WorkflowMetrics, WorkflowTask } from "@/types/workflows";

import { germany } from "./enterprise-fixtures";
import { healthyRoutes, jsonResponse, mockApi, page, type RecordedRequest } from "./fixtures";
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
  source: "code",
  status: "active",
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

  it("starts a stored workflow from a form generated from its input schema", async () => {
    const stored: WorkflowDefinition = {
      ...definition,
      workflow_id: "WF-1001",
      name: "Customer Address Change",
      source: "stored",
      steps: [{ id: "assign_key", type: "service_task", name: "Assign case reference", handler: "core.business_key", next: "done" }, { id: "done", type: "completion", name: "Done" }],
      input_schema: {
        type: "object",
        required: ["customer_number", "reason"],
        properties: {
          customer_number: { type: "string", pattern: "^CUS-[0-9]{7,}$" },
          reason: { type: "string", enum: ["moved", "correction"] },
          urgent: { type: "boolean" },
          floor: { type: "integer", minimum: 0 },
        },
      },
    };
    const started = { ...failedExecution, id: "new-2", workflow_id: "WF-1001", status: "completed", outcome: "updated", error: null, steps: [] };
    const api = mockApi(
      routes({
        "GET /api/v1/workflows": () => jsonResponse([definition, stored]),
        "GET /api/v1/workflows/WF-1001": () => jsonResponse(stored),
        "GET /api/v1/workflows/WF-1001/metrics": () => jsonResponse({ ...metrics, workflow_id: "WF-1001", steps: [] }),
        "GET /api/v1/workflow-definitions/handlers": () =>
          jsonResponse([{ name: "core.business_key", step_type: "service_task", summary: "", output: "", effect: "writes", requires_approval: false, params_schema: {} }]),
        "POST /api/v1/workflows/WF-1001/executions": () => jsonResponse(started, 201),
        "GET /api/v1/workflow-executions": () => jsonResponse(page([])),
        "GET /api/v1/workflow-executions/new-2": () => jsonResponse(started),
        "GET /api/v1/workflow-executions/new-2/history": () => jsonResponse([]),
      }),
    );
    renderApp("/workflows");

    const list = await screen.findByRole("list", { name: "Workflows" });
    await userEvent.click(await within(list).findByText("Customer Address Change"));
    expect(within(list).getByText("Stored")).toBeInTheDocument();
    expect(await screen.findByText("Handler core.business_key")).toBeInTheDocument();
    expect(await screen.findByText("Writes records")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start a case" }));
    const dialog = await screen.findByRole("dialog", { name: "Start Customer Address Change (WF-1001)" });
    await userEvent.type(within(dialog).getByLabelText("Customer number"), "CUS-0000042");
    await userEvent.selectOptions(within(dialog).getByLabelText("Reason"), "moved");
    await userEvent.click(within(dialog).getByLabelText("Urgent"));
    await userEvent.type(within(dialog).getByLabelText("Floor"), "3");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start case" }));

    await screen.findByRole("dialog", { name: "Workflow execution" });
    const post = api.requests.find((r) => r.method === "POST");
    expect(post?.body).toEqual({ input: { customer_number: "CUS-0000042", reason: "moved", urgent: true, floor: 3 } });
  });

  it("validates a definition, lists every problem and imports it", async () => {
    const problems = [
      { location: "steps.assign_key.handler", code: "unknown_handler", message: "'core.nope' is not in the handler library." },
      { location: "start", code: "unknown_step", message: "Start step 'x' does not exist." },
    ];
    let attempts = 0;
    let validations = 0;
    const api = mockApi(
      routes({
        "GET /api/v1/workflow-definitions/handlers": () =>
          jsonResponse([{ name: "accounts.charge_fee", step_type: "service_task", summary: "Charges a fee.", output: "", effect: "moves_money", requires_approval: true, params_schema: { properties: { amount: {} } } }]),
        "POST /api/v1/workflow-definitions/validate": () =>
          ++validations === 1
            ? jsonResponse({ valid: false, workflow_id: "WF-1002", version: 1, content_hash: "abc", existing: null, errors: problems, warnings: [] })
            : jsonResponse({ valid: true, workflow_id: "WF-1002", version: 1, content_hash: "abc", existing: "new", errors: [], warnings: [], effects: { charge_fee: "moves_money", notify: "writes" } }),
        "POST /api/v1/workflow-definitions": () =>
          ++attempts === 1
            ? jsonResponse({ error: { code: "definition_invalid", message: "The definition has 2 problem(s); nothing was imported.", details: { errors: problems, warnings: [] }, correlation_id: null } }, 422)
            : jsonResponse({ created: true, definition: { workflow_id: "WF-1002", version: 1 }, warnings: [] }, 201),
      }),
    );
    renderApp("/workflows");

    await userEvent.click(await screen.findByRole("button", { name: "Import definition" }));
    const dialog = screen.getByRole("dialog", { name: "Import a workflow definition" });
    const editor = within(dialog).getByLabelText("Definition (JSON)");
    await userEvent.type(editor, "not json");
    await userEvent.click(within(dialog).getByRole("button", { name: "Validate" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Not valid JSON");

    await userEvent.clear(editor);
    await userEvent.click(editor);
    await userEvent.paste('{"workflow_id": "WF-1002"}');
    await userEvent.click(within(dialog).getByRole("button", { name: "Validate" }));
    const errors = await within(dialog).findByRole("list", { name: "Errors" });
    expect(within(errors).getAllByRole("listitem")).toHaveLength(2);
    expect(within(errors).getByText("steps.assign_key.handler")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Validate" }));
    const effects = await within(dialog).findByRole("list", { name: "Effects" });
    expect(within(effects).getByText("Moves money").closest("li")).toHaveTextContent("charge_fee");
    expect(within(dialog).getByText(/approval required/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    expect(await within(dialog).findByRole("list", { name: "Errors" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Import" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const posts = api.requests.filter((r) => r.method === "POST" && r.path === "/api/v1/workflow-definitions");
    expect(posts.at(-1)?.body).toEqual({ definition: { workflow_id: "WF-1002" } });
  });

  it("previews and generates template variants, then opens one in the catalogue", async () => {
    const template = {
      id: "t1", template_id: "TPL-PAPER-STATEMENT", version: 1, name: "Paper statement request",
      description: "One workflow per country and product.", status: "active", content_hash: "h",
      id_range: [2000, 2999],
      parameters: { type: "object", properties: { country_code: { type: "string" }, account_type: { type: "string", enum: ["current", "savings"] }, fee: { type: "integer", minimum: 1, maximum: 10000 } } },
      example: { country_code: "GB", account_type: "current", fee: 5 },
      imported_by_username: "admin", imported_at: "2026-10-30T10:00:00Z", variants: 1,
    };
    const generated = (dry: boolean) => ({
      template_id: "TPL-PAPER-STATEMENT", template_version: 1, dry_run: dry, stored: !dry,
      created: 1, updated: 0, unchanged: 1, invalid: 0,
      results: [
        { variant_key: '{"account_type":"current","country_code":"GB","fee":5}', params: {}, workflow_id: "WF-2000", version: 1, status: "unchanged", errors: [] },
        { variant_key: '{"account_type":"current","country_code":"JP","fee":5}', params: {}, workflow_id: "WF-2001", version: 1, status: "created", errors: [] },
      ],
    });
    const variant = { ...definition, workflow_id: "WF-2000", name: "Paper Statements — United Kingdom, current accounts", source: "stored", template_id: "TPL-PAPER-STATEMENT", origin: { template_id: "TPL-PAPER-STATEMENT", template_version: 1, variant_key: "k" } };
    const api = mockApi(
      routes({
        "GET /api/v1/workflow-templates": () => jsonResponse([template]),
        "GET /api/v1/workflow-templates/TPL-PAPER-STATEMENT/variants": () =>
          jsonResponse([{ workflow_id: "WF-2000", variant_key: '{"account_type":"current","country_code":"GB","fee":5}', params: {}, template_version: 1, definition_version: 1, generated_at: "2026-10-30T10:00:00Z" }]),
        "POST /api/v1/workflow-templates/TPL-PAPER-STATEMENT/generate": (request: RecordedRequest) =>
          jsonResponse(generated(Boolean((request.body as { dry_run: boolean }).dry_run))),
        "GET /api/v1/workflows": (request: RecordedRequest) => jsonResponse(request.search.get("q") === "WF-2000" ? [variant] : [definition]),
        "GET /api/v1/workflows/WF-2000": () => jsonResponse(variant),
        "GET /api/v1/workflows/WF-2000/metrics": () => jsonResponse({ ...metrics, workflow_id: "WF-2000", steps: [] }),
        "GET /api/v1/workflow-definitions/handlers": () => jsonResponse([]),
      }),
    );
    renderApp("/workflows?tab=templates");

    const parameters = await screen.findByRole("table", { name: "Template parameters" });
    expect(within(parameters).getByText("current | savings")).toBeInTheDocument();
    expect(within(parameters).getByText("integer 1–10000")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Generate variants" }));
    const dialog = screen.getByRole("dialog", { name: "Generate variants of TPL-PAPER-STATEMENT" });
    expect(within(dialog).getByLabelText("Parameter sets (JSON)")).toHaveValue(JSON.stringify({ fixed: template.example }, null, 2));
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview" }));
    expect(await within(dialog).findByRole("status")).toHaveTextContent("Preview (nothing stored): 1 new, 0 updated, 1 unchanged, 0 invalid");
    await userEvent.click(within(dialog).getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(within(dialog).getByRole("status")).toHaveTextContent("Stored: 1 new"));
    const posts = api.requests.filter((r) => r.method === "POST").map((r) => (r.body as { dry_run: boolean }).dry_run);
    expect(posts).toEqual([true, false]);
    await userEvent.keyboard("{Escape}");

    const variants = screen.getByRole("table", { name: "Template variants" });
    await userEvent.click(await within(variants).findByText("WF-2000 v1"));
    expect(await screen.findByText(/Generated from TPL-PAPER-STATEMENT v1/)).toBeInTheDocument();
  });

  it("runs a stored workflow's generated tests and shows failures and gaps", async () => {
    const stored: WorkflowDefinition = { ...definition, workflow_id: "WF-1001", name: "Customer Address Change", source: "stored" };
    const run = {
      id: "run-1", workflow_id: "WF-1001", version: 1, passed: 13, failed: 1, skipped: 0,
      step_coverage: 1, route_coverage: 0.93, duration_ms: 1800, ran_at: "2026-10-30T12:00:00Z", ran_by_username: "admin",
      cases: [
        { name: "happy path", kind: "happy", route: null, status: "passed", detail: "", outcome: "updated", visited: [], mocked: [], ms: 90 },
        { name: "no-route probe at route_by_reason", kind: "route", route: null, status: "failed", detail: "ended badly: no_route at route_by_reason", outcome: null, visited: [], mocked: [], ms: 80 },
      ],
      uncovered: [{ route: "route_by_reason → colleague_review (transition[2])", reason: "case failed" }],
    };
    const api = mockApi(
      routes({
        "GET /api/v1/workflows": () => jsonResponse([stored]),
        "GET /api/v1/workflows/WF-1001": () => jsonResponse(stored),
        "GET /api/v1/workflows/WF-1001/metrics": () => jsonResponse({ ...metrics, workflow_id: "WF-1001", steps: [] }),
        "GET /api/v1/workflow-definitions/handlers": () => jsonResponse([]),
        "GET /api/v1/workflow-definitions/WF-1001/tests": () => jsonResponse([]),
        "POST /api/v1/workflow-definitions/WF-1001/versions/1/tests": () => jsonResponse(run),
      }),
    );
    renderApp("/workflows");

    const panel = await screen.findByRole("region", { name: "Generated tests" });
    expect(await within(panel).findByText("Not tested yet.")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Run tests on v1" }));
    expect(await within(panel).findByRole("status")).toHaveTextContent("13 passed, 1 failed · steps 100 % · routes 93 %");
    expect(within(panel).getByRole("list", { name: "Failing cases" })).toHaveTextContent("no_route at route_by_reason");
    expect(within(panel).getByRole("list", { name: "Uncovered routes" })).toHaveTextContent("transition[2]");
    expect(api.requests.some((r) => r.method === "POST" && r.path.endsWith("/versions/1/tests"))).toBe(true);
  });

  it("draws a workflow as a diagram with its coverage", async () => {
    const graphData = {
      workflow_id: "WF-0001", version: 1, layers: 3, tested_at: "2026-10-30T12:00:00Z",
      nodes: [
        { id: "receive_application", name: "Customer submits application", type: "service_task", layer: 0, order: 0, start: true, permissions: [], reachable: true, runs: 5, failed: 0 },
        { id: "account_approval", name: "Authorized approval", type: "approval", layer: 1, order: 0, start: false, permissions: ["accounts:approve"], reachable: true, runs: 5, failed: 1 },
        { id: "complete", name: "Case closed", type: "completion", layer: 2, order: 0, start: false, permissions: [], reachable: true, outcome: "approved" },
      ],
      edges: [
        { source: "receive_application", target: "account_approval", kind: "next", label: "", route: "r1", back: false, covered: true },
        { source: "account_approval", target: "complete", kind: "transition", label: "approved", route: "r2", back: false, covered: false },
      ],
    };
    mockApi(routes({ "GET /api/v1/workflows/WF-0001/graph": () => jsonResponse(graphData) }));
    renderApp("/workflows");

    await userEvent.click(await screen.findByRole("tab", { name: "Diagram" }));
    const diagram = await screen.findByRole("img", { name: "Diagram of WF-0001 v1" });
    expect(within(diagram).getByText("Authorized approval")).toBeInTheDocument();
    expect(within(diagram).getByText("5 (1)")).toBeInTheDocument();
    expect(within(diagram).getByText("approved")).toBeInTheDocument();
    expect(diagram.querySelector('[data-route="r2"]')?.getAttribute("data-covered")).toBe("false");
    expect(screen.getByText(/1 route\(s\) not covered/)).toBeInTheDocument();
  });

  it("edits a stored workflow with a live, located preview and saves the next version", async () => {
    const stored: WorkflowDefinition = { ...definition, workflow_id: "WF-1001", name: "Customer Address Change", source: "stored" };
    const exported = { ...stored, version: 1, steps: [
      { id: "assign_key", type: "service_task", name: "Assign case reference", handler: "core.business_key", params: { path: "input.customer_number" }, next: "done" },
      { id: "done", type: "completion", name: "Done", outcome: "updated" },
    ] };
    const node = (id: string, name: string, layer: number) => ({ id, name, type: "service_task", layer, order: 0, start: layer === 0, permissions: [], reachable: true });
    let previews = 0;
    const bodies: { definition: { steps: { id: string; name: string }[] } }[] = [];
    const api = mockApi(
      routes({
        "GET /api/v1/workflows": () => jsonResponse([stored]),
        "GET /api/v1/workflows/WF-1001": () => jsonResponse(stored),
        "GET /api/v1/workflows/WF-1001/metrics": () => jsonResponse({ ...metrics, workflow_id: "WF-1001", steps: [] }),
        "GET /api/v1/workflows/WF-1001/export": () => jsonResponse(exported),
        "GET /api/v1/workflow-definitions/handlers": () => jsonResponse([]),
        "GET /api/v1/workflow-definitions/WF-1001/tests": () => jsonResponse([]),
        "POST /api/v1/workflow-definitions/preview": (request: RecordedRequest) => {
          bodies.push(request.body as (typeof bodies)[number]);
          previews += 1;
          const valid = previews > 1;
          return jsonResponse({
            report: { valid, workflow_id: "WF-1001", version: 2, content_hash: "h", existing: valid ? "new" : null,
              errors: valid ? [] : [{ location: "steps.assign_key.params", code: "unknown_input_field", message: "reads an unknown input field" }], warnings: [], effects: {} },
            graph: { workflow_id: "WF-1001", version: 2, layers: 2, nodes: [node("assign_key", "Assign case reference", 0), node("done", "Done", 1)],
              edges: [{ source: "assign_key", target: "done", kind: "next", label: "", route: "a", back: false, covered: null }] },
          });
        },
        "POST /api/v1/workflow-definitions": () => jsonResponse({ created: true, definition: { workflow_id: "WF-1001", version: 2 }, warnings: [] }, 201),
      }),
    );
    renderApp("/workflows");

    await userEvent.click(await screen.findByRole("button", { name: "Edit as v2" }));
    const editor = await screen.findByRole("dialog", { name: "Edit WF-1001 as v2" });
    await waitFor(() => expect(within(editor).getByRole("status")).toHaveTextContent("1 problem(s) to fix before saving."));
    expect(within(editor).getByRole("button", { name: "Save as v2" })).toBeDisabled();
    const diagram = within(editor).getByRole("img", { name: "Diagram of WF-1001 v2" });
    expect(within(diagram).getByText("1 problem")).toBeInTheDocument();

    await userEvent.click(diagram.querySelector('[data-step="assign_key"]') as Element);
    const form = within(editor).getByRole("group", { name: "Step assign_key" });
    expect(within(form).getByRole("list", { name: "Step problems" })).toHaveTextContent("unknown input field");
    const name = within(form).getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Reference");
    await waitFor(() => expect(within(editor).getByRole("status")).toHaveTextContent("Valid: v2 can be saved."), { timeout: 3000 });
    expect(bodies.at(-1)?.definition.steps[0].name).toBe("Reference");

    await userEvent.click(within(editor).getByRole("button", { name: "Save as v2" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit WF-1001 as v2" })).not.toBeInTheDocument());
    const saved = api.requests.find((r) => r.method === "POST" && r.path === "/api/v1/workflow-definitions");
    expect((saved?.body as { definition: { version: number } }).definition.version).toBe(2);
  });
});
