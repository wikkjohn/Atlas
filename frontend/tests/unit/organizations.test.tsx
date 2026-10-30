import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Job } from "@/types/jobs";
import type { SubsidiaryBlueprint } from "@/types/enterprise";

import { asiaHq, bank } from "./enterprise-fixtures";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

function orgRoutes() {
  return {
    ...healthyRoutes,
    "GET /api/v1/organizations": (request: { search: URLSearchParams }) => {
      if (request.search.get("root_only") === "true") return jsonResponse(page([bank]));
      if (request.search.get("parent_id") === bank.id) return jsonResponse(page([asiaHq]));
      return jsonResponse(page([]));
    },
    "GET /api/v1/organizations/org-bank": () => jsonResponse(bank),
    "GET /api/v1/organizations/org-bank/ancestors": () => jsonResponse([]),
    "GET /api/v1/organizations/org-apac": () => jsonResponse(asiaHq),
    "GET /api/v1/organizations/org-apac/ancestors": () => jsonResponse([bank]),
    "GET /api/v1/countries": () => jsonResponse(page([])),
    "GET /api/v1/organizations/blueprint": () => jsonResponse(blueprint),
  };
}

const blueprint: SubsidiaryBlueprint = {
  version: 1,
  generated_from: "subsidiary-blueprint/1",
  regional_headquarters: {
    americas: "Americas Regional Headquarters",
    europe: "Europe Regional Headquarters",
    middle_east_africa: "Middle East & Africa Regional Headquarters",
    asia_pacific: "Asia-Pacific Regional Headquarters",
  },
  structure: { "Retail Banking": { "Customer Onboarding": ["KYC Review"] } },
  units_per_subsidiary: 12,
  staff_per_subsidiary: 24,
  usd_salary_band: [62_000, 240_000],
  coverage: [
    { region: "americas", countries: 22, subsidiaries: 1, generated: 0, without_subsidiary: ["AR", "BR"] },
    { region: "middle_east_africa", countries: 28, subsidiaries: 0, generated: 0, without_subsidiary: ["GH", "KE"] },
  ],
};

describe("Organization page", () => {
  it("shows subsidiary coverage and generates subsidiaries as a job", async () => {
    const job: Job = {
      id: "job-9",
      job_number: 9,
      kind: "organizations.generate",
      payload: { country_codes: ["GH", "KE"], staff: true },
      status: "succeeded",
      attempts: 1,
      max_attempts: 1,
      run_at: "2026-10-30T20:00:00Z",
      result: { countries: 2, launched: ["GH"], failed: { KE: "ATLAS Bank Kenya is inactive." }, organizations_created: 13, employees_hired: 24 },
      last_error: null,
      locked_by: null,
      schedule_name: null,
      created_by_username: "admin",
      created_at: "2026-10-30T20:00:00Z",
      started_at: "2026-10-30T20:00:00Z",
      finished_at: "2026-10-30T20:00:01Z",
    };
    const api = mockApi({
      ...orgRoutes(),
      "POST /api/v1/organizations/generate": () => jsonResponse({ ...job, status: "queued", result: null }, 202),
      "GET /api/v1/jobs/job-9": () => jsonResponse(job),
    });
    renderApp("/organization");

    const coverage = await screen.findByRole("table", { name: "Subsidiary coverage" });
    const mea = (await within(coverage).findByText("Middle East & Africa")).closest("tr") as HTMLElement;
    expect(within(mea).getByText("GH KE")).toBeInTheDocument();
    expect(screen.getByText(/Blueprint v1: 12 units and 24 synthetic staff/)).toBeInTheDocument();

    const form = screen.getByRole("form", { name: "Generate subsidiaries" });
    await userEvent.type(within(form).getByLabelText("Country codes"), "gh, ke");
    await userEvent.click(within(form).getByRole("button", { name: "Generate" }));
    const status = await screen.findByText(/Launched 1 of 2 countries: 13 organizations, 24 staff/);
    expect(status).toBeInTheDocument();
    expect(screen.getByText("KE: ATLAS Bank Kenya is inactive.")).toBeInTheDocument();
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({ country_codes: ["GH", "KE"], staff: true });
  });

  it("loads the hierarchy lazily and shows details for the selected unit", async () => {
    const api = mockApi(orgRoutes());
    renderApp("/organization");

    const tree = await screen.findByRole("list", { name: "Organization hierarchy" });
    await userEvent.click(await within(tree).findByRole("button", { name: /^Asia-Pacific HQ/ }));

    expect(await screen.findByRole("heading", { name: "Asia-Pacific HQ" })).toBeInTheDocument();
    expect(screen.getByText("ATLAS Global Bank", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Asia-Pacific", { selector: "dd" })).toBeInTheDocument();
    expect(
      api.requests.some((r) => r.path === "/api/v1/organizations" && r.search.get("parent_id") === bank.id),
    ).toBe(true);
    // The child type is decided by the parent's type.
    expect(screen.getByRole("button", { name: "Add country subsidiary" })).toBeInTheDocument();
  });

  it("surfaces business-rule violations from the API", async () => {
    mockApi({
      ...orgRoutes(),
      "POST /api/v1/organizations": () =>
        jsonResponse(
          {
            error: {
              code: "business_rule_violation",
              message: "A regional headquarters must specify its region.",
              details: null,
              correlation_id: "trace-7",
            },
          },
          422,
        ),
    });
    renderApp("/organization");

    await userEvent.click(await screen.findByRole("button", { name: "Add regional hq" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Middle East HQ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "A regional headquarters must specify its region.",
    );
  });

  it("offers no management actions to read-only roles", async () => {
    mockApi({ ...orgRoutes(), ...authRoutes(employeeUser) });
    renderApp("/organization");

    expect(await screen.findByRole("heading", { name: "ATLAS Global Bank" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Add / })).not.toBeInTheDocument();
  });
});
