import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, apiPut, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { Breach, CreditRating, Obligor, ProvisionLine, ProvisionRun, RiskSummary } from "@/types/risk";

export const RISK_PAGE = 25;

function useInvalidate() {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: ["risk"] });
}

export function useRiskSummary() {
  return useQuery({ queryKey: ["risk", "summary"], queryFn: () => apiGet<RiskSummary>("/api/v1/risk/summary/counts") });
}

/** An obligor's grade, limit and exposure; disabled until a customer number is given. */
export function useObligor(customerNumber: string) {
  return useQuery({
    queryKey: ["risk", "obligor", customerNumber],
    queryFn: () => apiGet<Obligor>(`/api/v1/risk/obligors/${encodeURIComponent(customerNumber)}`),
    enabled: customerNumber.length > 0,
    retry: false,
  });
}

export function useBreaches() {
  return useQuery({ queryKey: ["risk", "breaches"], queryFn: () => apiGet<Breach[]>("/api/v1/risk/breaches") });
}

export function useRatings(offset = 0) {
  return useQuery({
    queryKey: ["risk", "ratings", offset],
    queryFn: () => apiGet<Page<CreditRating>>(`/api/v1/risk/ratings${query({ limit: RISK_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  });
}

export function useProvisionRuns(offset = 0) {
  return useQuery({
    queryKey: ["risk", "provisions", offset],
    queryFn: () => apiGet<Page<ProvisionRun>>(`/api/v1/risk/provisions${query({ limit: RISK_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  });
}

export function useProvisionLines(runId: string | null) {
  return useQuery({
    queryKey: ["risk", "lines", runId],
    queryFn: () => apiGet<Page<ProvisionLine>>(`/api/v1/risk/provisions/${runId}/lines${query({ limit: 50 })}`),
    enabled: runId !== null,
  });
}

export function useRate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { customer_number: string; grade: number | null; rationale: string }) => apiPost<CreditRating>("/api/v1/risk/ratings", body),
    onSuccess: invalidate,
  });
}

export function useDecideRating() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => apiPost<CreditRating>(`/api/v1/risk/ratings/${id}/${approve ? "approve" : "reject"}`, {}),
    onSuccess: invalidate,
  });
}

export function useSetLimit() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { customer_number: string; limit_usd: number; note: string }) => apiPut<Obligor>("/api/v1/risk/limits", body),
    onSuccess: invalidate,
  });
}

export function useCalculate() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: () => apiPost<ProvisionRun>("/api/v1/risk/provisions", {}), onSuccess: invalidate });
}

export function useDecideRun() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, post }: { id: string; post: boolean }) =>
      apiPost<ProvisionRun>(`/api/v1/risk/provisions/${id}/${post ? "post" : "reject"}`, post ? {} : { note: "Rejected on review" }),
    onSuccess: invalidate,
  });
}
