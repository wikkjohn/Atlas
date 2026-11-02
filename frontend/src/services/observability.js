import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/services/api";
const REFRESH_MS = 10_000;
export const useObservability = () => useQuery({
    queryKey: ["observability", "overview"],
    queryFn: () => apiGet("/api/v1/observability/overview"),
    refetchInterval: REFRESH_MS,
});
/** Slow statements grouped by statement and route or job, worst total time first. */
export const useSlowQueries = () => useQuery({
    queryKey: ["observability", "slow-queries"],
    queryFn: () => apiGet("/api/v1/observability/slow-queries?grouped=true&limit=10"),
    refetchInterval: REFRESH_MS,
});
