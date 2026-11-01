import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { AmlAlert, ComplianceCase, ComplianceSummary, KycReview, MonitoringRun, Sar } from "@/types/compliance";
import type { Page } from "@/types/enterprise";

export const COMPLIANCE_PAGE = 25;

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["compliance"] });
    void client.invalidateQueries({ queryKey: ["customers"] });
  };
}

export function useComplianceSummary() {
  return useQuery({ queryKey: ["compliance", "summary"], queryFn: () => apiGet<ComplianceSummary>("/api/v1/compliance/summary/counts") });
}

export function useRuns() {
  return useQuery({ queryKey: ["compliance", "runs"], queryFn: () => apiGet<Page<MonitoringRun>>(`/api/v1/compliance/runs${query({ limit: 5 })}`) });
}

function paged<T>(path: string, key: string, offset: number, filters: Record<string, string | undefined> = {}) {
  return {
    queryKey: ["compliance", key, offset, filters],
    queryFn: () => apiGet<Page<T>>(`/api/v1/compliance/${path}${query({ limit: COMPLIANCE_PAGE, offset, ...filters })}`),
    placeholderData: keepPreviousData,
  };
}

/** A page of alerts, newest first; optionally only one account's. */
export function useAlerts(offset = 0, accountNumber = "") {
  return useQuery(paged<AmlAlert>("alerts", "alerts", offset, { account_number: accountNumber || undefined }));
}

export function useCases(offset = 0) {
  return useQuery(paged<ComplianceCase>("cases", "cases", offset));
}

export function useSars(offset = 0) {
  return useQuery(paged<Sar>("sars", "sars", offset));
}

export function useReviews(offset = 0) {
  return useQuery(paged<KycReview>("reviews", "reviews", offset));
}

export function useRunMonitoring() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (days: number) => apiPost<MonitoringRun>("/api/v1/compliance/runs", { days }), onSuccess: invalidate });
}

export function useAlertAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "investigate" | "dismiss" }) =>
      apiPost<AmlAlert | ComplianceCase>(`/api/v1/compliance/alerts/${id}/${action}`, action === "dismiss" ? { note: "False positive" } : {}),
    onSuccess: invalidate,
  });
}

export function useCaseAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "close" | "sar" }) =>
      apiPost<ComplianceCase | Sar>(`/api/v1/compliance/cases/${id}/${action}`, action === "close" ? { note: "No suspicion after investigation" } : {}),
    onSuccess: invalidate,
  });
}

export function useFileSar() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (id: string) => apiPost<Sar>(`/api/v1/compliance/sars/${id}/file`, {}), onSuccess: invalidate });
}

export function useScheduleReviews() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (horizon_days: number) => apiPost<{ opened: number }>("/api/v1/compliance/reviews/schedule", { horizon_days }), onSuccess: invalidate });
}

export function useCompleteReview() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, risk_rating }: { id: string; risk_rating: string }) => apiPost<KycReview>(`/api/v1/compliance/reviews/${id}/complete`, { risk_rating }),
    onSuccess: invalidate,
  });
}
