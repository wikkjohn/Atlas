import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost, query } from "@/services/api";
function useInvalidateRetail() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["retail"] });
        void client.invalidateQueries({ queryKey: ["accounts"] });
    };
}
export function useRetailSummary() {
    return useQuery({ queryKey: ["retail", "summary"], queryFn: () => apiGet("/api/v1/retail/summary") });
}
export function useRetailProducts() {
    return useQuery({ queryKey: ["retail", "products"], queryFn: () => apiGet("/api/v1/retail/products") });
}
export function useUpdateProduct() {
    const invalidate = useInvalidateRetail();
    return useMutation({
        mutationFn: ({ account_type, ...body }) => apiPatch(`/api/v1/retail/products/${account_type}`, body),
        onSuccess: invalidate,
    });
}
export function useStandingOrders(status) {
    return useQuery({
        queryKey: ["retail", "standing-orders", status],
        queryFn: () => apiGet(`/api/v1/retail/standing-orders${query({ status, limit: 25 })}`),
    });
}
export function useCreateStandingOrder() {
    const invalidate = useInvalidateRetail();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/retail/standing-orders", body),
        onSuccess: invalidate,
    });
}
export function useCancelStandingOrder() {
    const invalidate = useInvalidateRetail();
    return useMutation({
        mutationFn: (id) => apiPost(`/api/v1/retail/standing-orders/${id}/cancel`, {}),
        onSuccess: invalidate,
    });
}
export function useStatements() {
    return useQuery({
        queryKey: ["retail", "statements"],
        queryFn: () => apiGet(`/api/v1/retail/statements${query({ limit: 15 })}`),
    });
}
export function useStatement(id) {
    return useQuery({
        queryKey: ["retail", "statement", id],
        queryFn: () => apiGet(`/api/v1/retail/statements/${id}`),
        enabled: Boolean(id),
    });
}
export function useMonthEnds() {
    return useQuery({ queryKey: ["retail", "month-ends"], queryFn: () => apiGet("/api/v1/retail/month-ends") });
}
export function useRunMonthEnd() {
    const invalidate = useInvalidateRetail();
    return useMutation({
        mutationFn: (period) => apiPost("/api/v1/retail/month-ends", period ? { period } : {}),
        onSuccess: invalidate,
    });
}
