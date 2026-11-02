import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { authRoutes, employeeUser, healthyRoutes, jsonResponse, mockApi, page } from "./fixtures";
import { renderApp } from "./render";
const arrears = {
    loan_number: "LN-0000007",
    customer_number: "CUS-0000042",
    customer_name: "Synthetic Customer",
    currency: "USD",
    days_past_due: 44,
    amount: 89_000,
    instalments: 2,
    bucket: "dpd_31_60",
    oldest_due: "2040-02-10",
    plan_number: null,
    plan_status: null,
};
const plan = {
    id: "pln-1",
    plan_number: "PLN-0000001",
    loan_number: "LN-0000003",
    currency: "USD",
    status: "proposed",
    arrears_amount: 89_000,
    days_past_due: 44,
    payments: 2,
    interval_days: 14,
    schedule: [
        { n: 1, due: "2040-04-08", amount: 44_500, status: "due", on: null },
        { n: 2, due: "2040-04-22", amount: 44_500, status: "due", on: null },
    ],
    missed: 0,
    start_date: "2040-03-25",
    note: null,
    created_at: "2040-03-25T09:00:00Z",
};
const writtenOff = {
    loan_number: "LN-0000009",
    customer_number: "CUS-0000043",
    customer_name: "Another Customer",
    currency: "USD",
    written_off_on: "2040-05-15",
    written_off: 500_000,
    recovered: 100_000,
    remaining: 400_000,
};
const sale = {
    id: "rec-1",
    recovery_number: "REC-0000001",
    loan_number: "LN-0000009",
    kind: "debt_sale",
    amount: 100_000,
    currency: "USD",
    status: "recorded",
    entry_number: null,
    note: null,
    created_at: "2040-05-16T09:00:00Z",
};
const routes = {
    ...healthyRoutes,
    "GET /api/v1/collections/summary/counts": () => jsonResponse({ plans_proposed: 1, plans_active: 0, plans_broken: 0, plans_completed: 0, debt_sales_to_approve: 1, loans_written_off: 1 }),
    "GET /api/v1/collections/arrears": () => jsonResponse([arrears]),
    "GET /api/v1/collections/plans": () => jsonResponse(page([plan])),
    "GET /api/v1/collections/written-off": () => jsonResponse([writtenOff]),
    "GET /api/v1/collections/recoveries": () => jsonResponse(page([sale])),
};
describe("Collections page", () => {
    it("shows arrears, plans with their schedule, and written-off loans", async () => {
        mockApi(routes);
        renderApp("/collections");
        expect(await screen.findByLabelText("Collections summary")).toHaveTextContent("Plans to approve1");
        const arrearsTable = await screen.findByRole("table", { name: "Arrears" });
        expect((await within(arrearsTable).findByText("LN-0000007")).closest("tr")).toHaveTextContent("44 days past due · 2 instalments");
        const plans = await screen.findByRole("table", { name: "Plans" });
        expect((await within(plans).findByText("PLN-0000001")).closest("tr")).toHaveTextContent("2040-04-08 due");
        const written = await screen.findByRole("table", { name: "Written-off loans" });
        expect((await within(written).findByText("LN-0000009")).closest("tr")).toHaveTextContent("written off 2040-05-15");
    });
    it("proposes and approves a plan, takes payments, records and approves a recovery", async () => {
        const api = mockApi({
            ...routes,
            "POST /api/v1/collections/plans": () => jsonResponse({ ...plan, id: "pln-2", plan_number: "PLN-0000002", loan_number: "LN-0000007" }, 201),
            "POST /api/v1/collections/plans/pln-1/approve": () => jsonResponse({ ...plan, status: "active" }),
            "POST /api/v1/collections/plans/collect": () => jsonResponse({ as_of: "2040-04-08", plans: 1, paid: 1, missed: 0, completed: 0, broken: 0 }),
            "POST /api/v1/collections/recoveries": () => jsonResponse({ ...sale, id: "rec-2", kind: "payment", status: "posted" }, 201),
            "POST /api/v1/collections/recoveries/rec-1/approve": () => jsonResponse({ ...sale, status: "posted" }),
        });
        renderApp("/collections");
        await userEvent.clear(await screen.findByLabelText("Plan interval days"));
        await userEvent.type(screen.getByLabelText("Plan interval days"), "21");
        await userEvent.click(await screen.findByRole("button", { name: "Propose plan for LN-0000007" }));
        await userEvent.click(await screen.findByRole("button", { name: "Approve PLN-0000001" }));
        await userEvent.click(screen.getByRole("button", { name: "Take payments due" }));
        expect(await screen.findByText(/1 paid, 0 missed/)).toBeInTheDocument();
        await userEvent.type(screen.getByLabelText("Recovery amount for LN-0000009"), "250");
        await userEvent.click(screen.getByRole("button", { name: "Record recovery on LN-0000009" }));
        await userEvent.click(screen.getByRole("button", { name: "Approve REC-0000001" }));
        await waitFor(() => expect(api.requests.filter((r) => r.method !== "GET")).toHaveLength(5));
        const bodies = Object.fromEntries(api.requests.filter((r) => r.method !== "GET").map((r) => [`${r.method} ${r.path}`, r.body]));
        expect(bodies["POST /api/v1/collections/plans"]).toEqual({ loan_number: "LN-0000007", interval_days: 21 });
        expect(bodies["POST /api/v1/collections/recoveries"]).toEqual({ loan_number: "LN-0000009", kind: "payment", amount: 25_000 });
    });
    it("is read-only with only loans:read", async () => {
        mockApi({ ...routes, ...authRoutes({ ...employeeUser, permissions: ["loans:read"] }) });
        renderApp("/collections");
        expect(await screen.findByText("PLN-0000001")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Propose plan for LN-0000007" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Approve PLN-0000001" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Take payments due" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Approve REC-0000001" })).not.toBeInTheDocument();
    });
});
