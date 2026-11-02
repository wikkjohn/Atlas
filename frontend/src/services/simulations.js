import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query, useIdempotencyKey } from "@/services/api";
const POLL_MS = 2000;
const active = (status) => status === "queued" || status === "running";
export const useScenarios = () => useQuery({
    queryKey: ["simulations", "scenarios"],
    queryFn: () => apiGet("/api/v1/simulations/scenarios"),
    staleTime: Infinity,
});
export const useProfiles = () => useQuery({
    queryKey: ["simulations", "profiles"],
    queryFn: () => apiGet("/api/v1/simulations/profiles"),
    staleTime: Infinity,
});
export const useSimulationRuns = (offset, limit) => useQuery({
    queryKey: ["simulations", "runs", offset, limit],
    queryFn: () => apiGet(`/api/v1/simulations${query({ offset, limit })}`),
    placeholderData: keepPreviousData,
    // Keep polling while any listed run is still in progress.
    refetchInterval: (q) => (q.state.data?.items.some((r) => active(r.status)) ? POLL_MS : false),
});
/** `watch` keeps polling, e.g. while a queued archive or restore job has yet to finish. */
export const useSimulationRun = (id, watch = false) => useQuery({
    queryKey: ["simulations", "run", id],
    queryFn: () => apiGet(`/api/v1/simulations/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => (watch || active(q.state.data?.status) ? POLL_MS : false),
});
export const useHistoryOverview = () => useQuery({
    queryKey: ["simulations", "history"],
    queryFn: () => apiGet("/api/v1/simulations/history"),
});
/** Queue the archive (or restore) of a run's workflow history as a background job. */
export function useHistoryAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action }) => apiPost(`/api/v1/simulations/${id}/${action}`, {}),
        onSuccess: invalidate,
    });
}
export const useSimulationCases = (id, params, enabled) => useQuery({
    queryKey: ["simulations", "cases", id, params],
    queryFn: () => apiGet(`/api/v1/simulations/${id}/cases${query(params)}`),
    enabled: Boolean(id) && enabled,
    placeholderData: keepPreviousData,
});
function useInvalidate() {
    const client = useQueryClient();
    return () => void client.invalidateQueries({ queryKey: ["simulations"] });
}
export function useStartSimulation() {
    const invalidate = useInvalidate();
    const once = useIdempotencyKey();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/simulations", body, once.key()),
        onSuccess: () => {
            once.renew();
            invalidate();
        },
    });
}
export function useRerunSimulation() {
    const invalidate = useInvalidate();
    const once = useIdempotencyKey();
    return useMutation({
        mutationFn: (id) => apiPost(`/api/v1/simulations/${id}/rerun`, {}, once.key()),
        onSuccess: () => {
            once.renew();
            invalidate();
        },
    });
}
