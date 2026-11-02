import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
export const COMPLIANCE_PAGE = 25;
function useInvalidate() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["compliance"] });
        void client.invalidateQueries({ queryKey: ["customers"] });
    };
}
export function useComplianceSummary() {
    return useQuery({ queryKey: ["compliance", "summary"], queryFn: () => apiGet("/api/v1/compliance/summary/counts") });
}
export function useRuns() {
    return useQuery({ queryKey: ["compliance", "runs"], queryFn: () => apiGet(`/api/v1/compliance/runs${query({ limit: 5 })}`) });
}
function paged(path, key, offset, filters = {}) {
    return {
        queryKey: ["compliance", key, offset, filters],
        queryFn: () => apiGet(`/api/v1/compliance/${path}${query({ limit: COMPLIANCE_PAGE, offset, ...filters })}`),
        placeholderData: keepPreviousData,
    };
}
/** A page of alerts, newest first; optionally only one account's. */
export function useAlerts(offset = 0, accountNumber = "") {
    return useQuery(paged("alerts", "alerts", offset, { account_number: accountNumber || undefined }));
}
export function useCases(offset = 0) {
    return useQuery(paged("cases", "cases", offset));
}
export function useSars(offset = 0) {
    return useQuery(paged("sars", "sars", offset));
}
export function useReviews(offset = 0) {
    return useQuery(paged("reviews", "reviews", offset));
}
export function useRunMonitoring() {
    const invalidate = useInvalidate();
    return useMutation({ mutationFn: (days) => apiPost("/api/v1/compliance/runs", { days }), onSuccess: invalidate });
}
export function useAlertAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action }) => apiPost(`/api/v1/compliance/alerts/${id}/${action}`, action === "dismiss" ? { note: "False positive" } : {}),
        onSuccess: invalidate,
    });
}
export function useCaseAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action }) => apiPost(`/api/v1/compliance/cases/${id}/${action}`, action === "close" ? { note: "No suspicion after investigation" } : {}),
        onSuccess: invalidate,
    });
}
export function useFileSar() {
    const invalidate = useInvalidate();
    return useMutation({ mutationFn: (id) => apiPost(`/api/v1/compliance/sars/${id}/file`, {}), onSuccess: invalidate });
}
export function useScheduleReviews() {
    const invalidate = useInvalidate();
    return useMutation({ mutationFn: (horizon_days) => apiPost("/api/v1/compliance/reviews/schedule", { horizon_days }), onSuccess: invalidate });
}
export function useCompleteReview() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, risk_rating }) => apiPost(`/api/v1/compliance/reviews/${id}/complete`, { risk_rating }),
        onSuccess: invalidate,
    });
}
