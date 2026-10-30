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

  it("shows a country's reference data, calendar, format checks and samples", async () => {
    const reference = {
      ...japan,
      iso_alpha3: "JPN",
      calling_code: "+81",
      weekend_days: [6, 7],
      regulator: { name: "Financial Services Agency", abbreviation: "FSA" },
      identity_documents: [
        { type: "national_id", name: "My Number", mask: "9999 9999 9999", example: "1234 5678 9012" },
        { type: "passport", name: "Passport", mask: "AA9999999", example: "AB1234567" },
      ],
      address_format: {
        style: "postal_first",
        lines: ["{postal_code}", "{region} {city}", "{street}"],
        postal_code_masks: ["999-9999"],
        postal_code_example: "123-4567",
        requires_region: true,
      },
      reference_notes: ["Bridge holidays between two holidays are not modelled."],
      reference_version: "2026.1",
    };
    const api = mockApi({
      ...healthyRoutes,
      ...authRoutes(employeeUser),
      "/api/v1/countries": () => jsonResponse(page([reference])),
      "/api/v1/currencies": () => jsonResponse([{ code: "JPY", name: "Japanese yen", minor_units: 0 }]),
      [`/api/v1/countries/${japan.id}/calendar`]: () =>
        jsonResponse({
          iso_country_code: "JP",
          year: 2026,
          weekend_days: [6, 7],
          holidays: [
            { date: "2026-01-01", name: "New Year's Day", observed: "2026-01-01" },
            { date: "2026-05-03", name: "Constitution Memorial Day", observed: "2026-05-06" },
          ],
          business_days: 244,
          notes: [],
        }),
      [`/api/v1/countries/${japan.id}/samples`]: () =>
        jsonResponse([{ national_id: "0002 4879 8449", passport: "XZ7155980", postal_code: "796-5942", address_lines: ["796-5942", "Tokyo Testville", "59 Model Lane"] }]),
      [`POST /api/v1/countries/${japan.id}/check`]: () =>
        jsonResponse({ kind: "postal_code", value: "1234", valid: false, masks: ["999-9999"] }),
    });
    renderApp("/countries");

    await userEvent.click(await screen.findByRole("button", { name: "Japan" }));
    const dialog = screen.getByRole("dialog", { name: "Japan (JP)" });
    expect(within(dialog).getByText("Financial Services Agency (FSA)")).toBeInTheDocument();
    expect(await within(dialog).findByText("JPY · Japanese yen, 0 decimals")).toBeInTheDocument();
    expect(within(dialog).getByText("Saturday and Sunday")).toBeInTheDocument();
    expect(within(dialog).getByText("e.g. 1234 5678 9012")).toBeInTheDocument();
    const holidays = within(dialog).getByRole("region", { name: "Holiday calendar" });
    expect(await within(holidays).findByText("244 business days")).toBeInTheDocument();
    expect(within(holidays).getByText("(observed 2026-05-06)", { exact: false })).toBeInTheDocument();

    const check = within(dialog).getByRole("region", { name: "Check a value" });
    await userEvent.type(within(check).getByLabelText("Value"), "1234");
    await userEvent.click(within(check).getByRole("button", { name: "Check" }));
    expect(await within(check).findByRole("status")).toHaveTextContent("1234 does not match 999-9999");
    expect(api.requests.find((r) => r.method === "POST")?.body).toEqual({ kind: "postal_code", value: "1234" });
    expect(await within(dialog).findByText("ID 0002 4879 8449")).toBeInTheDocument();
    expect(within(dialog).getByText("Bridge holidays between two holidays are not modelled.")).toBeInTheDocument();
  });
});
