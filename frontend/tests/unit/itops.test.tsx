import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Application, ChangeRequest, Incident } from "@/types/itops";

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

const routes = {
  ...healthyRoutes,
  "GET /api/v1/itops/summary/counts": () =>
    jsonResponse({ applications: 12, incidents_open: 1, p1_open: 1, incidents_breached: 0, incidents_to_close: 1, changes_to_approve: 1, changes_scheduled: 1, changes_failed_30d: 0, frozen_now: true }),
  "GET /api/v1/itops/applications": () => jsonResponse(page([app, desk])),
  "GET /api/v1/itops/estate/summary": () =>
    jsonResponse({ applications: 2512, dependencies: 6015, unconnected: 78, generated: 2500, by_tier: { "1": 243, "2": 913, "3": 1356 }, by_technology: {}, by_hosting: {} }),
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

  it("is read-only with only itops:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["itops:read"] }) });
    renderApp("/it-operations");
    expect(await screen.findByText("INC-0000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Report incident" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Raise change" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge INC-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve CHG-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Generate estate" })).not.toBeInTheDocument();
  });
});
