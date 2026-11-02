import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost, query, useIdempotencyKey } from "@/services/api";
function useInvalidate() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["ai-tools"] });
        void client.invalidateQueries({ queryKey: ["simulations"] });
    };
}
export const useAiTools = () => useQuery({
    queryKey: ["ai-tools", "list"],
    queryFn: () => apiGet(`/api/v1/ai-tools${query({ limit: 100 })}`),
});
export const useAiTool = (id) => useQuery({
    queryKey: ["ai-tools", "detail", id],
    queryFn: () => apiGet(`/api/v1/ai-tools/${id}`),
    enabled: Boolean(id),
});
export const useAdapters = () => useQuery({
    queryKey: ["ai-tools", "adapters"],
    queryFn: () => apiGet("/api/v1/ai-tools/adapters"),
    staleTime: Infinity,
});
export const useActions = () => useQuery({
    queryKey: ["ai-tools", "actions"],
    queryFn: () => apiGet("/api/v1/ai-tools/actions"),
    staleTime: Infinity,
});
export const useInvocations = (tool, offset, limit) => useQuery({
    queryKey: ["ai-tools", "invocations", tool, offset, limit],
    queryFn: () => apiGet(`/api/v1/ai-tools/invocations${query({ tool, offset, limit })}`),
    enabled: Boolean(tool),
    placeholderData: keepPreviousData,
});
export const useSuiteRuns = (batchId) => useQuery({
    queryKey: ["simulations", "suite", batchId],
    queryFn: () => apiGet(`/api/v1/simulations${query({ batch_id: batchId, limit: 10 })}`),
    enabled: Boolean(batchId),
    refetchInterval: (q) => q.state.data?.items.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false,
});
export function useRegisterTool() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/ai-tools", body),
        onSuccess: invalidate,
    });
}
export function useSetToolStatus() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, status }) => apiPatch(`/api/v1/ai-tools/${id}`, { status }),
        onSuccess: invalidate,
    });
}
export function useInvokeTool(id) {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost(`/api/v1/ai-tools/${id}/invoke`, body),
        onSettled: invalidate,
    });
}
export function useStartSuite() {
    const invalidate = useInvalidate();
    const once = useIdempotencyKey();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/simulations/suites", body, once.key()),
        onSuccess: () => {
            once.renew();
            invalidate();
        },
    });
}
