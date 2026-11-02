import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
export const WEALTH_PAGE = 25;
function useInvalidate() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["wealth"] });
        void client.invalidateQueries({ queryKey: ["accounts"] });
    };
}
export function useWealthSummary() {
    return useQuery({ queryKey: ["wealth", "summary"], queryFn: () => apiGet("/api/v1/wealth/summary/counts") });
}
export function useSecurities() {
    return useQuery({ queryKey: ["wealth", "securities"], queryFn: () => apiGet("/api/v1/wealth/securities") });
}
/** A page of portfolios, newest first. */
export function usePortfolios(offset = 0) {
    return useQuery({
        queryKey: ["wealth", "portfolios", offset],
        queryFn: () => apiGet(`/api/v1/wealth/portfolios${query({ limit: WEALTH_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    });
}
export function useValuation(portfolioNumber) {
    return useQuery({
        queryKey: ["wealth", "valuation", portfolioNumber],
        queryFn: () => apiGet(`/api/v1/wealth/portfolios/${portfolioNumber}/valuation`),
        enabled: Boolean(portfolioNumber),
    });
}
/** A page of orders, newest first. */
export function useOrders(offset = 0) {
    return useQuery({
        queryKey: ["wealth", "orders", offset],
        queryFn: () => apiGet(`/api/v1/wealth/orders${query({ limit: WEALTH_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    });
}
export function useDistributions() {
    return useQuery({
        queryKey: ["wealth", "distributions"],
        queryFn: () => apiGet(`/api/v1/wealth/distributions${query({ limit: 10 })}`),
    });
}
export function useRecordProfile() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/wealth/profiles", body),
        onSuccess: invalidate,
    });
}
export function useOpenPortfolio() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (account_number) => apiPost("/api/v1/wealth/portfolios", { account_number }),
        onSuccess: invalidate,
    });
}
export function useClosePortfolio() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (portfolioNumber) => apiPost(`/api/v1/wealth/portfolios/${portfolioNumber}/close`, {}),
        onSuccess: invalidate,
    });
}
export function usePlaceOrder() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/wealth/orders", body),
        onSuccess: invalidate,
    });
}
export function useOrderAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action }) => apiPost(`/api/v1/wealth/orders/${id}/${action}`, action === "approve" ? { note: "Insistent client" } : action === "reject" ? { note: "Unsuitable for the customer" } : {}),
        onSuccess: invalidate,
    });
}
export function useDistribute() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (security_code) => apiPost("/api/v1/wealth/distributions", { security_code }),
        onSuccess: invalidate,
    });
}
