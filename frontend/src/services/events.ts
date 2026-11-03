import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { AccessGrant, DomainEvent, EventDelivery, EventSummary } from "@/types/events";

/** Phase 74: the event pipeline (jobs:read) and Information Security's access grants. */
export const useEventSummary = () =>
  useQuery({ queryKey: ["events", "summary"], queryFn: () => apiGet<EventSummary>("/api/v1/events/summary") });

export const useStuckEvents = () =>
  useQuery({
    queryKey: ["events", "stuck"],
    queryFn: async () => {
      const [failed, dead] = await Promise.all([
        apiGet<DomainEvent[]>(`/api/v1/events${query({ status: "failed", limit: 20 })}`),
        apiGet<DomainEvent[]>(`/api/v1/events${query({ status: "dead", limit: 20 })}`),
      ]);
      const seen = new Set<string>();
      return [...dead, ...failed].filter((e) => (seen.has(e.id) ? false : (seen.add(e.id), true)));
    },
  });

export function useRetryDelivery() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<EventDelivery>(`/api/v1/events/deliveries/${id}/retry`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["events"] }),
  });
}

export const useAccessGrants = (status: string) =>
  useQuery({
    queryKey: ["access", "grants", status],
    queryFn: () => apiGet<AccessGrant[]>(`/api/v1/access/grants${query({ status: status || undefined })}`),
  });

export function useGrantAccess() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<AccessGrant>(`/api/v1/access/grants/${id}/grant`, {}),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["access"] });
      void client.invalidateQueries({ queryKey: ["employees"] });
    },
  });
}
