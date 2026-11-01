import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { AmlAlert, ComplianceCase, KycReview, Sar } from "@/types/compliance";

import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const alert = (overrides: Partial<AmlAlert>): AmlAlert => ({
  id: "alr-1",
  alert_number: "ALR-0000001",
  customer_number: "CUS-0000042",
  customer_name: "Synthetic Customer",
  account_number: "US000000000101",
  rule: "structuring",
  score: 70,
  currency: "USD",
  amount: 2_770_000,
  details: {},
  window_start: "2026-10-03",
  window_end: "2026-11-01",
  status: "open",
  case_number: null,
  note: null,
  created_at: "2026-11-01T08:00:00Z",
  ...overrides,
});
const investigating: ComplianceCase = {
  id: "case-1",
  case_number: "CASE-0000001",
  customer_number: "CUS-0000043",
  customer_name: "Another Customer",
  status: "investigating",
  alerts: ["ALR-0000002"],
  sar_number: null,
  note: null,
  created_at: "2026-11-01T09:00:00Z",
};
const draft: Sar = {
  id: "sar-1",
  sar_number: "SAR-0000001",
  case_number: "CASE-0000000",
  customer_number: "CUS-0000044",
  narrative: "Activity flagged by transaction monitoring.",
  currency: "USD",
  amount: 2_770_000,
  status: "draft",
  filing_reference: null,
  created_at: "2026-11-01T09:30:00Z",
  filed_at: null,
};
const review: KycReview = {
  id: "kyr-1",
  review_number: "KYR-0000001",
  customer_number: "CUS-0000045",
  customer_name: "High Risk Customer",
  due_on: "2026-11-10",
  status: "due",
  risk_before: "high",
  risk_after: null,
  outcome: null,
  completed_on: null,
};

const routes = {
  ...healthyRoutes,
  "GET /api/v1/compliance/summary/counts": () => jsonResponse({ open_alerts: 1, open_cases: 1, draft_sars: 1, filed_sars: 0, reviews_due: 1, reviews_overdue: 0 }),
  "GET /api/v1/compliance/runs": () => jsonResponse(page([{ id: "run-1", run_number: "MON-0000001", window_start: "2026-10-03", window_end: "2026-11-01", accounts_scanned: 120, alerts_raised: 3, created_at: "2026-11-01T08:00:00Z" }])),
  "GET /api/v1/compliance/alerts": () => jsonResponse(page([alert({}), alert({ id: "alr-2", alert_number: "ALR-0000002", rule: "rapid_movement", status: "in_case", case_number: "CASE-0000001" })])),
  "GET /api/v1/compliance/cases": () => jsonResponse(page([investigating])),
  "GET /api/v1/compliance/sars": () => jsonResponse(page([draft])),
  "GET /api/v1/compliance/reviews": () => jsonResponse(page([review])),
};

describe("Compliance page", () => {
  it("shows the latest run, alerts, cases, reports and reviews", async () => {
    mockApi(routes);
    renderApp("/compliance");
    const alerts = await screen.findByRole("table", { name: "Alerts" });
    expect((await within(alerts).findByText("ALR-0000001")).closest("tr")).toHaveTextContent("Structuring (score 70) · Synthetic Customer (CUS-0000042)");
    expect(within(alerts).getByText("ALR-0000002").closest("tr")).toHaveTextContent("Rapid movement of funds");
    expect(screen.getByLabelText("Latest run")).toHaveTextContent("MON-0000001: 2026-10-03 to 2026-11-01, 120 accounts, 3 alerts");
    expect(screen.getByRole("table", { name: "Cases" })).toHaveTextContent("Another Customer (CUS-0000043) · ALR-0000002");
    expect(screen.getByRole("table", { name: "Suspicious activity reports" })).toHaveTextContent("CASE-0000000 · Activity flagged");
    expect(screen.getByRole("table", { name: "KYC reviews" })).toHaveTextContent("due 2026-11-10 · rated high");
  });

  it("runs monitoring, investigates and dismisses alerts, decides cases, files a report and completes a review", async () => {
    const api = mockApi({
      ...routes,
      "POST /api/v1/compliance/runs": () => jsonResponse({ id: "run-2", run_number: "MON-0000002", window_start: "2026-10-26", window_end: "2026-11-01", accounts_scanned: 40, alerts_raised: 0, created_at: "2026-11-01T10:00:00Z" }, 201),
      "POST /api/v1/compliance/alerts/alr-1/investigate": () => jsonResponse({ ...investigating, id: "case-2" }),
      "POST /api/v1/compliance/cases/case-1/sar": () => jsonResponse(draft, 201),
      "POST /api/v1/compliance/sars/sar-1/file": () => jsonResponse({ ...draft, status: "filed", filing_reference: "FIU-2026-0000001" }),
      "POST /api/v1/compliance/reviews/kyr-1/complete": () => jsonResponse({ ...review, status: "completed", outcome: "lowered", risk_after: "medium" }),
    });
    renderApp("/compliance");
    const run = await screen.findByRole("form", { name: "Run monitoring" });
    await userEvent.clear(within(run).getByLabelText("Window days"));
    await userEvent.type(within(run).getByLabelText("Window days"), "7");
    await userEvent.click(within(run).getByRole("button", { name: "Run monitoring" }));
    await userEvent.click(await screen.findByRole("button", { name: "Investigate ALR-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "Escalate CASE-0000001" }));
    await userEvent.click(screen.getByRole("button", { name: "File SAR-0000001" }));
    await userEvent.selectOptions(screen.getByLabelText("Rating for KYR-0000001"), "medium");
    await userEvent.click(screen.getByRole("button", { name: "Complete KYR-0000001" }));
    await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(5));
    const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
    expect(bodies["POST /api/v1/compliance/runs"]).toEqual({ days: 7 });
    expect(bodies["POST /api/v1/compliance/reviews/kyr-1/complete"]).toEqual({ risk_rating: "medium" });
  });

  it("pages back to older alerts beyond the newest 25", async () => {
    const api = mockApi({
      ...routes,
      "GET /api/v1/compliance/alerts": (request) =>
        request.search.get("offset") === "25" ? jsonResponse(page([alert({ id: "alr-old", alert_number: "ALR-0000099" })], 26, 25, 25)) : jsonResponse(page([alert({})], 26, 25, 0)),
    });
    renderApp("/compliance");
    const pages = await screen.findByRole("navigation", { name: "Alert pages" });
    await userEvent.click(within(pages).getByRole("button", { name: "Older" }));
    expect(await screen.findByText("ALR-0000099")).toBeInTheDocument();
    expect(api.requests.some((r) => r.path === "/api/v1/compliance/alerts" && r.search.get("offset") === "25")).toBe(true);
  });

  it("filters alerts by account", async () => {
    const api = mockApi(routes);
    renderApp("/compliance");
    await userEvent.type(await screen.findByLabelText("Alerts for account"), "us000000000101");
    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/v1/compliance/alerts" && r.search.get("account_number") === "US000000000101")).toBe(true));
  });

  it("is read-only without the monitoring and filing permissions", async () => {
    mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["compliance:read"] }) });
    renderApp("/compliance");
    expect(await screen.findByText("ALR-0000001")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Run monitoring" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Investigate ALR-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "File SAR-0000001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete KYR-0000001" })).not.toBeInTheDocument();
  });
});
