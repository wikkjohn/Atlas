import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Drilldown, DrilldownFigures } from "@/types/analytics";

import { healthyRoutes, jsonResponse, mockApi } from "./fixtures";
import { renderApp } from "./render";

const figures = (executions: number, partial: Partial<DrilldownFigures> = {}): DrilldownFigures => ({
  executions,
  completed: executions,
  failed: 0,
  active: 0,
  failure_rate: 0,
  avg_duration_s: 600,
  last_started_at: "2026-11-04T12:00:00Z",
  open_tasks: 0,
  ...partial,
});

const base = { realm: "all" as const, days: null, generated_at: "2026-11-05T12:00:00Z", scope: null, steps: null, outcomes: null, attribution: {} };
const bank = { level: "enterprise" as const, key: "enterprise", label: "ATLAS Global Bank" };

const levels: Record<string, Drilldown> = {
  enterprise: {
    ...base,
    level: "enterprise",
    path: [bank],
    summary: figures(9, { failed: 1, failure_rate: 0.125, open_tasks: 1 }),
    breakdown_by: "country",
    breakdown: [
      { key: "KE", label: "Kenya", ...figures(8, { failed: 1, failure_rate: 0.1429 }) },
      { key: "none", label: "Not attributed", ...figures(1) },
    ],
  },
  country: {
    ...base,
    level: "country",
    path: [bank, { level: "country", key: "KE", label: "Kenya" }],
    summary: figures(8),
    breakdown_by: "department",
    breakdown: [{ key: "Retail Banking", label: "Retail Banking", ...figures(8) }],
  },
  department: {
    ...base,
    level: "department",
    path: [bank, { level: "country", key: "KE", label: "Kenya" }, { level: "department", key: "Retail Banking", label: "Retail Banking" }],
    summary: figures(8),
    breakdown_by: "workflow",
    breakdown: [{ key: "WF-3040", label: "Overdraft — Kenya", ...figures(8) }],
  },
  workflow: {
    ...base,
    level: "workflow",
    path: [
      bank,
      { level: "country", key: "KE", label: "Kenya" },
      { level: "department", key: "Retail Banking", label: "Retail Banking" },
      { level: "workflow", key: "WF-3040", label: "Overdraft — Kenya" },
    ],
    summary: figures(8, { open_tasks: 2 }),
    breakdown_by: null,
    breakdown: [],
    steps: [
      { step_id: "check", step_type: "service_task", runs: 8, failed: 1, waiting: 0, avg_ms: 120, p95_ms: 300 },
      { step_id: "approve", step_type: "approval", runs: 7, failed: 0, waiting: 2, avg_ms: 90_000, p95_ms: 240_000 },
    ],
    outcomes: { approved: 5, rejected: 1, none: 2 },
  },
};

function levelOf(search: URLSearchParams): string {
  if (search.get("workflow_id")) return "workflow";
  if (search.get("department")) return "department";
  if (search.get("country")) return "country";
  return "enterprise";
}

describe("Drill-down (Phase 88)", () => {
  it("goes from the bank to a country, a department and a workflow, and back", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/analytics/drilldown": (r) => jsonResponse(levels[levelOf(r.search)]),
    });
    renderApp("/drilldown");

    const countries = await screen.findByRole("table", { name: "Executions by country" });
    expect(within(countries).getByText("14.3%")).toBeInTheDocument();
    expect(screen.getByLabelText("Summary")).toHaveTextContent("12.5%");
    await userEvent.click(within(countries).getByRole("link", { name: "Kenya" }));

    const departments = await screen.findByRole("table", { name: "Executions by department" });
    await userEvent.click(within(departments).getByRole("link", { name: "Retail Banking" }));
    const workflows = await screen.findByRole("table", { name: "Executions by workflow" });
    expect(within(workflows).getByText("WF-3040")).toBeInTheDocument();
    await userEvent.click(within(workflows).getByRole("link", { name: "Overdraft — Kenya" }));

    const steps = await screen.findByRole("table", { name: "Steps" });
    expect(within(steps).getByText("1.5 min")).toBeInTheDocument();
    expect(within(steps).getByText("4.0 min")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Outcomes" })).toHaveTextContent("No outcome yet2");
    const crumbs = screen.getByRole("navigation", { name: "Drill-down path" });
    expect(within(crumbs).getByText("Overdraft — Kenya")).toHaveAttribute("aria-current", "page");
    const last = api.requests.filter((r) => r.path === "/api/v1/analytics/drilldown").at(-1)!;
    expect(Object.fromEntries(last.search)).toEqual({ realm: "all", country: "KE", department: "Retail Banking", workflow_id: "WF-3040" });

    // A breadcrumb goes back up, keeping the path above it.
    await userEvent.click(within(crumbs).getByRole("link", { name: "Kenya" }));
    expect(await screen.findByRole("table", { name: "Executions by department" })).toBeInTheDocument();
  });

  it("filters by history and period, and says when the view is scoped", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/analytics/drilldown": () => jsonResponse({ ...levels.enterprise, scope: { countries: ["KE"], departments: null } }),
    });
    renderApp("/drilldown");
    expect(await screen.findByRole("note")).toHaveTextContent("Limited to your scope: countries KE");
    await userEvent.selectOptions(screen.getByLabelText("History"), "simulation");
    await userEvent.selectOptions(screen.getByLabelText("Period"), "30");
    const last = () => api.requests.filter((r) => r.path === "/api/v1/analytics/drilldown").at(-1)!;
    await screen.findByRole("table", { name: "Executions by country" });
    expect(last().search.get("realm")).toBe("simulation");
    expect(last().search.get("days")).toBe("30");
  });
});
