import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Application, ChangeRequest, Incident, Outage } from "@/types/itops";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const app: Application = {
  id: "app-1",
  application_number: "APP-00001",
  name: "Core Banking Ledger",
  description: "Accounts, balances and the general ledger",
  department: "Customer Onboarding",
  tier: 1,
  status: "active",
  open_incidents: 1,
  owner: "Ada Okafor",
  technology: "Java",
  hosting: "on_premise",
  vendor: null,
  generated_from: null,
};
const desk: Application = { ...app, id: "app-2", application_number: "APP-00005", name: "Loan Origination", tier: 2, open_incidents: 0 };
const incident: Incident = {
  id: "inc-1",
  incident_number: "INC-0000001",
  application_number: "APP-00001",
  application: "Core Banking Ledger",
  tier: 1,
  title: "Ledger postings failing",
  impact: "high",
  urgency: "high",
  priority: 1,
  status: "open",
  respond_by: "2026-11-02T09:15:00Z",
  resolve_by: "2026-11-02T13:00:00Z",
  acknowledged_at: null,
  resolved_at: null,
  response_breached: true,
  resolution_breached: false,
  resolution: null,
  review: null,
  change_number: null,
  created_at: "2026-11-02T09:00:00Z",
};
const resolved: Incident = { ...incident, id: "inc-2", incident_number: "INC-0000002", status: "resolved", response_breached: false, resolution: "Restarted the posting service.", change_number: "CHG-0000003" };
const change: ChangeRequest = {
  id: "chg-1",
  change_number: "CHG-0000001",
  application_number: "APP-00001",
  application: "Core Banking Ledger",
  tier: 1,
  title: "Upgrade the database driver",
  kind: "normal",
  risk: "high",
  needs_cab: true,
  planned_start: "2026-11-05T22:00:00Z",
  planned_end: "2026-11-06T00:00:00Z",
  incident_number: null,
  status: "requested",
  created_at: "2026-11-02T09:00:00Z",
};
const scheduled: ChangeRequest = { ...change, id: "chg-2", change_number: "CHG-0000002", application: "Loan Origination", tier: 2, risk: "medium", needs_cab: false, status: "approved" };

const outage: Outage = {
  id: "out-1",
  outage_number: "OUT-0000001",
  application_number: "APP-00001",
  application: "Core Banking Ledger",
  tier: 1,
  kind: "down",
  reason: "Storage array failed",
  starts_at: "2026-11-03T09:00:00Z",
  ends_at: null,
  status: "in_force",
  incident_number: "INC-0000009",
  failing: 1238,
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/itops/summary/counts": () =>
    jsonResponse({ applications: 12, incidents_open: 1, p1_open: 1, incidents_breached: 0, incidents_to_close: 1, changes_to_approve: 1, changes_scheduled: 1, changes_failed_30d: 0, frozen_now: true }),
  "GET /api/v1/itops/applications": () => jsonResponse(page([app, desk])),
  "GET /api/v1/itops/estate/summary": () =>
    jsonResponse({ applications: 2512, dependencies: 6015, unconnected: 78, generated: 2500, by_tier: { "1": 243, "2": 913, "3": 1356 }, by_technology: {}, by_hosting: {} }),
  "GET /api/v1/itops/outages": () => jsonResponse(page([outage])),
  "GET /api/v1/itops/applications/app-1/contract": () =>
    jsonResponse({
      application_number: "APP-00001",
      median_ms: { read: 40, write: 60 },
      p95_ms: { read: 91.1, write: 136.6 },
      error_rate: 0.0005,
      timeout_ms: 5000,
      sync_dependencies: 0,
      operations: ["read", "write"],
      state: { status: "down", cause: "APP-00001", path: ["APP-00001"] },
      blast_radius: 1238,
    }),
  "GET /api/v1/itops/estate/exit": () =>
    jsonResponse({
      passed: true,
      checks: { generated: true, wired: true, outage_measured: true },
      target: 2500,
      generated: 2500,
      wiring: { workflows_linked: 119, workflows: 119, steps_linked: 544, links: 1283, applications: 2526, called_directly: 341, wired: 2526, unwired: 0 },
      outage: { run_number: 10, scenario_id: "domestic-payments-outage", cases: 300, outages: ["Core Banking Ledger", "Payments Gateway"], executions_failed: 19, executions_delayed: 0 },
    }),
  "GET /api/v1/itops/estate/wiring": () =>
    jsonResponse({ workflows_linked: 119, workflows: 119, steps_linked: 544, links: 1270, applications: 2525, called_directly: 340, wired: 1105, unwired: 1420 }),
  "GET /api/v1/itops/applications/app-1/workflows": () =>
    jsonResponse({
      calls: 2,
      workflows: [{ workflow_id: "WF-1002", name: "Paper Statement Request", department: "Retail Banking", steps: ["Check the account is the customer's"] }],
      outage: {
        applications_failing: 1248,
        workflows_stopped: 117,
        workflows_linked: 119,
        steps_stopped: 479,
        by_department: { "Payments Operations": 4, Finance: 4 },
        workflows: [{ workflow_id: "WF-0002", name: "Domestic Payment", department: "Payments Operations", steps: ["Release"], via: ["APP-00001", "APP-00002"] }],
      },
    }),
  "GET /api/v1/itops/applications/app-1": () =>
    jsonResponse({
      application: app,
      dependencies: [],
      dependents: [{ id: "dep-1", kind: "api", application_number: "APP-00005", name: "Loan Origination", tier: 2, application_id: "app-2" }],
      impact: { affected: 2255, direct: 39, depth: 7, by_tier: { "1": 200, "2": 800, "3": 1255 }, departments: 21, top_departments: [], sample: [] },
    }),
  "GET /api/v1/itops/incidents": () => jsonResponse(page([incident, resolved])),
  "GET /api/v1/itops/changes": () => jsonResponse(page([change, scheduled])),
};

describe("IT Operations page", () => {
  it("shows the summary, the freeze, incidents with their targets, changes and the catalogue", async () => {
    mockApi(routes);
    renderApp("/it-operations");
    expect(await screen.findByLabelText("IT operations summary")).toHaveTextContent("Open P1s1");
    expect(screen.getByRole("note")).toHaveTextContent("Month-end freeze");
    const p1 = (await screen.findByText("INC-0000001")).closest("tr");
    expect(p1).toHaveTextContent("P1");
    expect(p1).toHaveTextContent("response late");
    expect(screen.getByText("INC-0000002").closest("tr")).toHaveTextContent("caused by CHG-0000003");
    expect(screen.getByText("CHG-0000001").closest("tr")).toHaveTextContent("executive approval");
    expect(screen.getByText("CHG-0000001").closest("tr")).toHaveTextContent("high risk");
    const apps = screen.getByRole("table", { name: "Applications" });
    expect(within(apps).getByText("APP-00001").closest("tr")).toHaveTextContent("tier 1");
  });

  it("reports and works incidents, raises, approves and implements changes", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/itops/incidents": () => jsonResponse({ ...incident, id: "inc-3", incident_number: "INC-0000003", priority: 2 }, 201),
      "POST /api/v1/itops/incidents/inc-1/acknowledge": () => jsonResponse({ ...incident, status: "acknowledged" }),
      "POST /api/v1/itops/incidents/inc-2/close": () => jsonResponse({ ...resolved, status: "closed" }),
      "POST /api/v1/itops/changes": () => jsonResponse({ ...change, id: "chg-3", change_number: "CHG-0000004", risk: "medium" }, 201),
      "POST /api/v1/itops/changes/chg-1/approve": () => jsonResponse({ ...change, status: "approved" }),
      "POST /api/v1/itops/changes/chg-2/implement": () => jsonResponse({ ...scheduled, status: "failed" }),
    });
    renderApp("/it-operations");
    const report = await screen.findByRole("form", { name: "Report incident" });
    await within(within(report).getByLabelText("Incident application")).findByRole("option", { name: /Loan Origination/ });
    await userEvent.selectOptions(within(report).getByLabelText("Incident application"), "APP-00005");
    await userEvent.type(within(report).getByLabelText("What is wrong"), "Applications not saving");
    await userEvent.selectOptions(within(report).getByLabelText("Impact"), "high");
    await userEvent.click(within(report).getByRole("button", { name: "Report incident" }));
    expect(await within(report).findByRole("status")).toHaveTextContent("INC-0000003 opened: P2");
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge INC-0000001" }));
    await userEvent.type(screen.getByLabelText("Review for INC-0000002"), "Root cause: a full disk on the host.");
    await userEvent.click(screen.getByRole("button", { name: "Close INC-0000002" }));

    const form = screen.getByRole("form", { name: "Raise change" });
    await userEvent.selectOptions(within(form).getByLabelText("Change application"), "APP-00005");
    await userEvent.type(within(form).getByLabelText("What changes"), "Patch the loan desk");
    await userEvent.type(within(form).getByLabelText("Backout plan"), "Roll back the patch.");
    await userEvent.click(within(form).getByRole("button", { name: "Raise change" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("CHG-0000004 requested: medium risk");
    await userEvent.click(screen.getByRole("button", { name: "Approve CHG-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Failed CHG-0000002" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(6));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/itops/incidents"]).toMatchObject({ application_number: "APP-00005", title: "Applications not saving", impact: "high", urgency: "medium" });
    expect(bodies["POST /api/v1/itops/incidents/inc-2/close"]).toMatchObject({ review: "Root cause: a full disk on the host." });
    expect(bodies["POST /api/v1/itops/changes"]).toMatchObject({ application_number: "APP-00005", kind: "normal", backout_plan: "Roll back the patch." });
    expect(bodies["POST /api/v1/itops/changes/chg-2/implement"]).toMatchObject({ success: false });
  });

  it("shows the registry: the estate, an application's links and what stops if it stops", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/itops/estate/generate": () => jsonResponse({ created: 2500, existing: 0, dependencies_added: 6015, seconds: 2.2 }),
    });
    renderApp("/it-operations");
    expect(await screen.findByLabelText("Estate summary")).toHaveTextContent("2512 applications (2500 generated) · 6015 dependencies");
    await userEvent.click(await screen.findByRole("button", { name: "Show APP-00001" }));
    const detail = await screen.findByRole("region", { name: "Application detail" });
    expect(await within(detail).findByLabelText("If it stops")).toHaveTextContent("2255 applications affected (39 directly, up to 7 steps away");
    expect(within(detail).getByLabelText("If it stops")).toHaveTextContent("across 21 departments");
    expect(within(detail).getByRole("list", { name: "Relied on by" })).toHaveTextContent("APP-00005 Loan Origination · api · tier 2");
    expect(detail).toHaveTextContent("Java on on premise");
    const flows = within(detail).getByRole("region", { name: "Workflows" });
    expect(await within(flows).findByRole("list", { name: "Calling workflows" })).toHaveTextContent("WF-1002 Paper Statement Request · Retail Banking");
    expect(within(flows).getByLabelText("If it goes down")).toHaveTextContent("117 of 119 workflows stop (479 steps, 1248 applications failing) · most in Payments Operations (4), Finance (4)");
    expect(within(flows).getByRole("list", { name: "Stopped workflows" })).toHaveTextContent("WF-0002 Domestic Payment · 1 step · through APP-00001, APP-00002");
    expect(screen.getByLabelText("Milestone E exit")).toHaveTextContent(
      "Milestone E exit passed2500 of 2500 generated · 0 unwired · outage measured in run #10 (domestic-payments-outage: 19 of 300 executions failed)",
    );
    expect(screen.getByLabelText("Wiring")).toHaveTextContent("119 workflows call 340 applications directly in 544 steps; 1105 of 2525 applications are wired");

    await userEvent.type(screen.getByLabelText("Search applications"), "Ledger");
    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/v1/itops/applications" && r.search.get("q") === "Ledger")).toBe(true));
    const generate = screen.getByRole("form", { name: "Generate estate" });
    await userEvent.click(within(generate).getByRole("button", { name: "Generate estate" }));
    expect(await within(generate).findByRole("status")).toHaveTextContent("2500 created, 6015 dependencies in 2.2 s");
    const body = api.requests.find((r) => r.method === "POST")?.body;
    expect(body).toEqual({ count: 2500, seed: 2030 });
    // The forms list the bank's own applications, within the API's page limit of 200.
    const choices = api.requests.find((r) => r.path === "/api/v1/itops/applications" && r.search.get("generated") === "false");
    expect(Number(choices?.search.get("limit"))).toBeLessThanOrEqual(200);
  });

  it("shows a simulated application's contract and state, tests calls, declares and ends outages", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/itops/applications/app-1/calls": () =>
        jsonResponse({ application_number: "APP-00001", operation: "read", calls: 100, seed: 2030, ok: 0, failed: 100, errors: { outage: 100 }, p50_ms: 50, p95_ms: 5000, max_ms: 5000, state: { status: "down", cause: "APP-00001", path: ["APP-00001"] } }),
      "POST /api/v1/itops/outages": () => jsonResponse({ ...outage, id: "out-2", outage_number: "OUT-0000002", application: "Loan Origination", kind: "degraded", failing: 0, incident_number: "INC-0000010" }, 201),
      "POST /api/v1/itops/outages/out-1/end": () => jsonResponse({ ...outage, status: "ended", ends_at: "2026-11-03T10:00:00Z" }),
    });
    renderApp("/it-operations");
    const outages = await screen.findByRole("table", { name: "Outages" });
    expect(await within(outages).findByText("OUT-0000001")).toBeInTheDocument();
    expect(within(outages).getByText("OUT-0000001").closest("tr")).toHaveTextContent("1238 applications fail");
    expect(within(outages).getByText("OUT-0000001").closest("tr")).toHaveTextContent("In force");

    await userEvent.click(await screen.findByRole("button", { name: "Show APP-00001" }));
    const sim = await screen.findByRole("region", { name: "Simulated application" });
    expect(await within(sim).findByLabelText("Contract")).toHaveTextContent("Read 40 ms median, 91.1 ms p95");
    expect(within(sim).getByLabelText("Contract")).toHaveTextContent("1238 applications fail if it goes down");
    expect(sim).toHaveTextContent("down");
    await userEvent.click(within(sim).getByRole("button", { name: "Test 100 calls" }));
    expect(await within(sim).findByRole("status")).toHaveTextContent("0 ok, 100 failed (100 outage)");

    const form = screen.getByRole("form", { name: "Declare outage" });
    await within(within(form).getByLabelText("Outage application")).findByRole("option", { name: /Loan Origination/ });
    await userEvent.selectOptions(within(form).getByLabelText("Outage application"), "APP-00005");
    await userEvent.selectOptions(within(form).getByLabelText("Outage kind"), "degraded");
    await userEvent.type(within(form).getByLabelText("Outage reason"), "Connection pool exhausted");
    await userEvent.click(within(form).getByRole("button", { name: "Declare outage" }));
    expect(await within(form).findByRole("status")).toHaveTextContent("OUT-0000002 degraded");
    await userEvent.click(screen.getByRole("button", { name: "End OUT-0000001" }));

    await waitFor(() => expect(api.requests.filter((r) => r.method === "POST")).toHaveLength(3));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method === "POST").map((r) => [r.path, r.body]));
    expect(bodies["/api/v1/itops/applications/app-1/calls"]).toEqual({ operation: "read", count: 100, seed: 2030 });
    expect(bodies["/api/v1/itops/outages"]).toEqual({ application_number: "APP-00005", kind: "degraded", reason: "Connection pool exhausted" });
  });

  it("is read-only with only itops:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["itops:read"] }) });
    renderApp("/it-operations");
    expect(await screen.findByText("INC-0000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Report incident" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Raise change" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge INC-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve CHG-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Generate estate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Declare outage" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End OUT-0000001" })).not.toBeInTheDocument();
  });
});
