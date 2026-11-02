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
  "GET /api/v1/itops/applications": () => jsonResponse([app, desk]),
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

  it("is read-only with only itops:read", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["itops:read"] }) });
    renderApp("/it-operations");
    expect(await screen.findByText("INC-0000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Report incident" })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Raise change" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge INC-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve CHG-0000001" })).not.toBeInTheDocument();
  });
});
