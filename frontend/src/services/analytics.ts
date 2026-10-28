import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/services/api";
import type { AnalyticsOverview } from "@/types/analytics";

export const useAnalyticsOverview = () =>
  useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: () => apiGet<AnalyticsOverview>("/api/v1/analytics/overview"),
    refetchInterval: 30_000,
  });
