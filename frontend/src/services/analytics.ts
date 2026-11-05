import { useQuery } from "@tanstack/react-query";

import { apiGet } from "@/services/api";
import type { AnalyticsOverview, Drilldown, DrilldownQuery } from "@/types/analytics";

export const useAnalyticsOverview = () =>
  useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: () => apiGet<AnalyticsOverview>("/api/v1/analytics/overview"),
    refetchInterval: 30_000,
  });

/** Phase 88: the drill-down at one place in the hierarchy. */
export function useDrilldown(query: DrilldownQuery) {
  const params = new URLSearchParams({ realm: query.realm });
  if (query.country) params.set("country", query.country);
  if (query.department) params.set("department", query.department);
  if (query.workflow_id) params.set("workflow_id", query.workflow_id);
  if (query.days) params.set("days", String(query.days));
  return useQuery({
    queryKey: ["analytics", "drilldown", params.toString()],
    queryFn: () => apiGet<Drilldown>(`/api/v1/analytics/drilldown?${params}`),
  });
}
