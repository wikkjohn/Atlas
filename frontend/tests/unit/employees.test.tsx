import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { analyst, manager } from "./enterprise-fixtures";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

const restricted = { ...analyst, annual_compensation: null, compensation_currency: null };

function routes(list = [manager, analyst]) {
  return {
    ...healthyRoutes,
    "GET /api/v1/employees": () => jsonResponse(page(list, list.length, 25)),
    "GET /api/v1/employees/emp-2": () => jsonResponse(list[1]),
    "GET /api/v1/employees/emp-2/reporting-chain": () => jsonResponse([manager]),
    "GET /api/v1/employees/emp-2/direct-reports": () => jsonResponse([]),
    "GET /api/v1/organizations": () => jsonResponse(page([])),
    "GET /api/v1/roles": () => jsonResponse([]),
  };
}

describe("Employees page", () => {
  it("formats compensation in the employee's currency", async () => {
    mockApi(routes());
    renderApp("/employees");

    const row = (await screen.findByText("Ren Ito")).closest("tr") as HTMLElement;
    // JPY has no minor unit: 6,500,000 minor units is ¥6,500,000.
    expect(within(row).getByText("¥6,500,000")).toBeInTheDocument();
  });

  it("shows compensation as restricted when the API withholds it", async () => {
    mockApi({ ...routes([manager, restricted]), ...authRoutes(employeeUser) });
    renderApp("/employees");

    const row = (await screen.findByText("Ren Ito")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Restricted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hire employee" })).not.toBeInTheDocument();
  });

  it("opens a profile with the reporting chain", async () => {
    mockApi(routes());
    renderApp("/employees");

    await userEvent.click(await screen.findByRole("button", { name: "Ren Ito" }));

    const dialog = await screen.findByRole("dialog", { name: "Employee profile" });
    const chain = await within(dialog).findByRole("region", { name: "Reporting chain" });
    expect(within(chain).getByRole("button", { name: "Aiko Tanaka" })).toBeInTheDocument();
    expect(within(dialog).getByText(/AGB-0000002/)).toBeInTheDocument();
  });

  it("sends the search term to the API", async () => {
    const api = mockApi(routes());
    renderApp("/employees");

    await userEvent.type(await screen.findByRole("textbox", { name: "Search employees" }), "tanaka{enter}");

    await screen.findByText("Ren Ito");
    expect(api.requests.some((r) => r.path === "/api/v1/employees" && r.search.get("q") === "tanaka")).toBe(true);
  });
});
