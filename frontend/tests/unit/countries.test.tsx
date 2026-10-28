import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { germany, japan } from "./enterprise-fixtures";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";

describe("Countries page", () => {
  it("lists the registry read-only for roles without manage permission", async () => {
    mockApi({
      ...healthyRoutes,
      ...authRoutes(employeeUser),
      "/api/v1/countries": () => jsonResponse(page([germany, japan])),
    });
    renderApp("/countries");

    const row = (await screen.findByText("Japan")).closest("tr") as HTMLElement;
    expect(within(row).getByText("JPY")).toBeInTheDocument();
    expect(within(row).getByText("Asia/Tokyo")).toBeInTheDocument();
    expect(within(row).getByText("active")).toBeInTheDocument();
    expect(screen.getByText("2 configured · target 120")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add country" })).not.toBeInTheDocument();
  });

  it("lets an administrator add a country with an idempotency key", async () => {
    const api = mockApi({
      ...healthyRoutes,
      "GET /api/v1/countries": () => jsonResponse(page([japan])),
      "POST /api/v1/countries": () => jsonResponse({ ...germany, operational_status: "planned" }, 201),
    });
    renderApp("/countries");

    await userEvent.click(await screen.findByRole("button", { name: "Add country" }));
    const dialog = screen.getByRole("dialog", { name: "Add country" });
    await userEvent.type(within(dialog).getByLabelText("ISO code"), "de");
    await userEvent.type(within(dialog).getByLabelText("Country name"), "Germany");
    await userEvent.type(within(dialog).getByLabelText("Currency"), "eur");
    await userEvent.type(within(dialog).getByLabelText("Time zone"), "Europe/Berlin");
    await userEvent.type(within(dialog).getByLabelText("Languages"), "de-DE, en");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add country" }));

    await screen.findByText("Japan");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const post = api.requests.find((r) => r.method === "POST");
    expect(post?.body).toMatchObject({
      iso_country_code: "DE",
      default_currency: "EUR",
      supported_languages: ["de-DE", "en"],
      region: "europe",
      operational_status: "planned",
    });
    expect(post?.headers["Idempotency-Key"]).toMatch(/.{8,}/);
  });

  it("shows the API's validation errors in the form", async () => {
    mockApi({
      ...healthyRoutes,
      "GET /api/v1/countries": () => jsonResponse(page([])),
      "POST /api/v1/countries": () =>
        jsonResponse(
          {
            error: {
              code: "validation_error",
              message: "Request validation failed.",
              details: [{ location: ["body", "default_timezone"], message: "not an IANA time zone", type: "value_error" }],
              correlation_id: "trace-9",
            },
          },
          422,
        ),
    });
    renderApp("/countries");

    await userEvent.click(await screen.findByRole("button", { name: "Add country" }));
    const dialog = screen.getByRole("dialog", { name: "Add country" });
    for (const [label, value] of [
      ["ISO code", "FR"],
      ["Country name", "France"],
      ["Currency", "EUR"],
      ["Time zone", "Paris"],
      ["Languages", "fr"],
    ]) {
      await userEvent.type(within(dialog).getByLabelText(label), value);
    }
    await userEvent.click(within(dialog).getByRole("button", { name: "Add country" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("default_timezone: not an IANA time zone");
    expect(alert).toHaveTextContent("Reference: trace-9");
  });
});
