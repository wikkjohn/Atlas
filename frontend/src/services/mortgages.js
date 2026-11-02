import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
import { toMinorUnits } from "@/services/format";
function useInvalidateMortgages() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["mortgages"] });
        void client.invalidateQueries({ queryKey: ["loans"] });
        void client.invalidateQueries({ queryKey: ["accounts"] });
    };
}
export function useMortgageSummary() {
    return useQuery({ queryKey: ["mortgages", "summary"], queryFn: () => apiGet("/api/v1/mortgages/summary/counts") });
}
export function useMortgageProducts() {
    return useQuery({ queryKey: ["mortgages", "products"], queryFn: () => apiGet("/api/v1/mortgages/products") });
}
export function useProperties() {
    return useQuery({
        queryKey: ["mortgages", "properties"],
        queryFn: () => apiGet(`/api/v1/mortgages/properties${query({ limit: 25 })}`),
    });
}
export function useOffers() {
    return useQuery({
        queryKey: ["mortgages", "offers"],
        queryFn: () => apiGet(`/api/v1/mortgages/offers${query({ limit: 25 })}`),
    });
}
/** The currency of a customer (their country's), looked up by customer number. */
export async function customerCurrency(number) {
    // The server matches customer numbers case-insensitively; so does this lookup.
    const wanted = number.trim().toUpperCase();
    const found = await apiGet(`/api/v1/customers${query({ q: wanted, limit: 5 })}`);
    const customer = found.items.find((c) => c.customer_number.toUpperCase() === wanted);
    if (!customer)
        throw new Error(`No customer ${number}.`);
    return customer.currency;
}
export function useRegisterProperty() {
    const invalidate = useInvalidateMortgages();
    return useMutation({
        // The price is entered in major units of the customer's currency.
        mutationFn: async ({ purchase_price_major, ...body }) => {
            const currency = await customerCurrency(body.customer_number);
            return apiPost("/api/v1/mortgages/properties", { ...body, purchase_price: toMinorUnits(purchase_price_major, currency) });
        },
        onSuccess: invalidate,
    });
}
export function useValueProperty() {
    const invalidate = useInvalidateMortgages();
    return useMutation({
        mutationFn: ({ id, ...body }) => apiPost(`/api/v1/mortgages/properties/${id}/valuations`, body),
        onSuccess: invalidate,
    });
}
export function useQuote() {
    return useMutation({ mutationFn: (body) => apiPost("/api/v1/mortgages/quote", body) });
}
export function useRequestOffer() {
    const invalidate = useInvalidateMortgages();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/mortgages/offers", body),
        onSuccess: invalidate,
    });
}
export function useOfferAction() {
    const invalidate = useInvalidateMortgages();
    return useMutation({
        mutationFn: ({ id, action, approve }) => apiPost(`/api/v1/mortgages/offers/${id}/${action}`, action === "decide" ? { approve } : {}),
        onSuccess: invalidate,
    });
}
