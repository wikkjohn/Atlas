import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDownload, apiGet, apiPost, query } from "@/services/api";
export const FINANCE_PAGE = 10;
function useInvalidate() {
    const client = useQueryClient();
    return () => void client.invalidateQueries({ queryKey: ["finance"] });
}
function paged(path, offset) {
    return {
        queryKey: ["finance", path, offset],
        queryFn: () => apiGet(`/api/v1/finance/${path}${query({ limit: FINANCE_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    };
}
export function useFinanceSummary() {
    return useQuery({ queryKey: ["finance", "summary"], queryFn: () => apiGet("/api/v1/finance/summary/counts") });
}
export const useCloses = (offset = 0) => useQuery(paged("closes", offset));
export const useReports = (offset = 0) => useQuery(paged("reports", offset));
export const useAllocations = (offset = 0) => useQuery(paged("allocations", offset));
export const useJournals = (offset = 0) => useQuery(paged("journals", offset));
export function usePrepareClose() {
    const invalidate = useInvalidate();
    return useMutation({ mutationFn: (period) => apiPost("/api/v1/finance/closes", { period }), onSuccess: invalidate });
}
export function useDecideClose() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, approve }) => apiPost(`/api/v1/finance/closes/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
        onSuccess: invalidate,
    });
}
export function usePrepareReport() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/finance/reports", body),
        onSuccess: invalidate,
    });
}
export function useDecideReport() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, submit }) => apiPost(`/api/v1/finance/reports/${id}/${submit ? "submit" : "reject"}`, submit ? {} : { note: "Rejected on review" }),
        onSuccess: invalidate,
    });
}
export async function downloadReportCsv(report) {
    const blob = await apiDownload(`/api/v1/finance/reports/${report.id}/csv`);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${report.report_number}-${report.report_type}-${report.period}.csv`;
    link.click();
    URL.revokeObjectURL(url);
}
export function useRecordExpense() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/finance/expenses", body),
        onSuccess: invalidate,
    });
}
export function useCalculateAllocation() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/finance/allocations", body),
        onSuccess: invalidate,
    });
}
export function useDecideAllocation() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, post }) => apiPost(`/api/v1/finance/allocations/${id}/${post ? "post" : "reject"}`, post ? {} : { note: "Rejected on review" }),
        onSuccess: invalidate,
    });
}
export function useProposeJournal() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/finance/journals", body),
        onSuccess: invalidate,
    });
}
export function useDecideJournal() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, approve }) => apiPost(`/api/v1/finance/journals/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
        onSuccess: invalidate,
    });
}
