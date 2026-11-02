import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
export const SERVICE_PAGE = 25;
const BASE = "/api/v1/customer-service";
function useInvalidate() {
    const client = useQueryClient();
    return () => void client.invalidateQueries({ queryKey: ["customer-service"] });
}
export function useServiceSummary() {
    return useQuery({ queryKey: ["customer-service", "summary"], queryFn: () => apiGet(`${BASE}/summary/counts`) });
}
/** A page of cases, most urgent first; `status` is "unresolved" or a status. */
export function useCases(offset = 0, status = "unresolved") {
    return useQuery({
        queryKey: ["customer-service", "cases", offset, status],
        queryFn: () => apiGet(`${BASE}/cases${query({ limit: SERVICE_PAGE, offset, status: status || undefined })}`),
        placeholderData: keepPreviousData,
    });
}
export function useOpenCase() {
    const invalidate = useInvalidate();
    return useMutation({ mutationFn: (body) => apiPost(`${BASE}/cases`, body), onSuccess: invalidate });
}
export function useCaseAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action, message }) => apiPost(`${BASE}/cases/${id}/${action}`, action === "respond" ? { message: message ?? "Thank you, we are looking into this." } : {}),
        onSuccess: invalidate,
    });
}
export function useProposeRedress() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, amount, account_number }) => apiPost(`${BASE}/cases/${id}/redress`, { amount, account_number }),
        onSuccess: invalidate,
    });
}
export function useResolveCase() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, resolution, outcome }) => apiPost(`${BASE}/cases/${id}/resolve`, { resolution, outcome }),
        onSuccess: invalidate,
    });
}
export function useSweep() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: () => apiPost(`${BASE}/sweep`, {}),
        onSuccess: invalidate,
    });
}
