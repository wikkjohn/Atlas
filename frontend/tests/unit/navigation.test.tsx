import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { NAV_ITEMS } from "@/app/navigation";

import { authRoutes, employeeUser, healthyRoutes, mockApi } from "./fixtures";
import { renderApp } from "./render";

describe("Application shell", () => {
  it("links live screens and shows later phases disabled", async () => {
    mockApi(healthyRoutes);
    renderApp();

    const nav = await screen.findByRole("navigation", { name: "Primary" });
    for (const item of NAV_ITEMS) {
      expect(within(nav).getByText(item.label)).toBeInTheDocument();
    }
    const links = within(nav).getAllByRole("link").map((link) => link.textContent);
    expect(links).toEqual([
      "Overview",
      "Organization",
      "Countries",
      "Employees",
      "Customers",
      "Accounts",
      "Audit Center",
    ]);

    const workflows = within(nav).getByText("Workflow Explorer").closest("[aria-disabled]");
    expect(workflows).toHaveAttribute("aria-disabled", "true");
    expect(workflows).toHaveTextContent("Phase 4");
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    expect(screen.getByText("Demo Platform Administrator")).toBeInTheDocument();
  });

  it("hides screens the signed-in role cannot use", async () => {
    mockApi({ ...healthyRoutes, ...authRoutes(employeeUser) });
    renderApp();

    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("Audit Center")).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Employees" })).toBeInTheDocument();
  });

  it("shows a not-found page for unknown routes and navigates back", async () => {
    mockApi(healthyRoutes);
    renderApp("/no-such-page");

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Back to overview" }));
    expect(await screen.findByRole("heading", { name: "Platform Overview" })).toBeInTheDocument();
  });
});
