import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/services/api";
export const useAnalyticsOverview = () => useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: () => apiGet("/api/v1/analytics/overview"),
    refetchInterval: 30_000,
});
