import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDownload, apiGet, apiPost, query, useIdempotencyKey } from "@/services/api";
const POLL_MS = 2000;
export const useExperiments = (offset, limit) => useQuery({
    queryKey: ["experiments", "list", offset, limit],
    queryFn: () => apiGet(`/api/v1/experiments${query({ offset, limit })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((e) => e.status === "running") ? POLL_MS : false),
});
export const useExperiment = (id) => useQuery({
    queryKey: ["experiments", "detail", id],
    queryFn: () => apiGet(`/api/v1/experiments/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
});
export const useBenchmarks = () => useQuery({
    queryKey: ["experiments", "benchmarks"],
    queryFn: () => apiGet("/api/v1/benchmarks"),
});
export function useCreateExperiment() {
    const client = useQueryClient();
    const once = useIdempotencyKey();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/experiments", body, once.key()),
        onSuccess: () => {
            once.renew();
            void client.invalidateQueries({ queryKey: ["experiments"] });
            void client.invalidateQueries({ queryKey: ["simulations"] });
        },
    });
}
export function useReEvaluate(id) {
    return useMutation({
        mutationFn: () => apiPost(`/api/v1/experiments/${id}/re-evaluate`, {}),
    });
}
/** Download the experiment's report through the authenticated API. */
export async function downloadReport(id, number, format) {
    const blob = await apiDownload(`/api/v1/experiments/${id}/report${query({ format })}`);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `atlas-experiment-${number}.${format === "json" ? "json" : "md"}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}
