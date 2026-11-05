/** Phase 85: the audit-log archive, data retention, unlocking users. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost } from "@/services/api";
import type { UserAccount } from "@/types/enterprise";
import type { ArchivedEvent, ArchiveVerification, AuditArchive, RetentionReview } from "@/types/governance";

export function useAuditArchives() {
  return useQuery({ queryKey: ["audit-archives"], queryFn: () => apiGet<AuditArchive[]>("/api/v1/audit-archives") });
}

export function useCreateArchive() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (olderThanDays: number) =>
      apiPost<AuditArchive | null>("/api/v1/audit-archives", { older_than_days: olderThanDays }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["audit-archives"] });
      void client.invalidateQueries({ queryKey: ["audit-events"] });
    },
  });
}

export function useVerifyArchive() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<ArchiveVerification>(`/api/v1/audit-archives/${id}/verify`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["audit-archives"] }),
  });
}

export function useArchivedEvents(id: string | null, action: string) {
  const params = new URLSearchParams({ limit: "50" });
  if (action) params.set("action", action);
  return useQuery({
    queryKey: ["audit-archives", id, "events", action],
    queryFn: () =>
      apiGet<{ items: ArchivedEvent[]; total: number }>(`/api/v1/audit-archives/${id}/events?${params}`),
    enabled: Boolean(id),
  });
}

export function useRetentionReview() {
  return useQuery({ queryKey: ["data-retention"], queryFn: () => apiGet<RetentionReview>("/api/v1/data-retention") });
}

export function useApplyRetention() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ run_number: number; results: Record<string, Record<string, number | null>> }>(
        "/api/v1/data-retention/apply",
        {},
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["data-retention"] });
      void client.invalidateQueries({ queryKey: ["audit-archives"] });
    },
  });
}

export function useUnlockUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost<UserAccount>(`/api/v1/users/${id}/unlock`, {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["users"] }),
  });
}
