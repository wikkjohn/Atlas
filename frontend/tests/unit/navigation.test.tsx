import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { NAV_ITEMS } from "@/app/navigation";

import { healthyRoutes, mockApi } from "./fixtures";
import { renderApp } from "./render";

describe("Application shell", () => {
  it("lists every global navigation entry and only links implemented screens", async () => {
    mockApi(healthyRoutes);
    renderApp();

    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const item of NAV_ITEMS) {
      expect(within(nav).getByText(item.label)).toBeInTheDocument();
    }
    expect(within(nav).getAllByRole("link")).toHaveLength(1);
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/");

    const workflows = within(nav).getByText("Workflow Explorer").closest("[aria-disabled]");
    expect(workflows).toHaveAttribute("aria-disabled", "true");
    expect(workflows).toHaveTextContent("Phase 4");
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
  });

  it("shows a not-found page for unknown routes and navigates back", async () => {
    mockApi(healthyRoutes);
    renderApp("/no-such-page");

    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Back to overview" }));
    expect(await screen.findByRole("heading", { name: "Platform Overview" })).toBeInTheDocument();
  });
});
