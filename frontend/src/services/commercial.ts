import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { CommercialSummary, CovenantTest, Facility, FacilityReview } from "@/types/commercial";
import type { Page } from "@/types/enterprise";

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["commercial"] });
    void client.invalidateQueries({ queryKey: ["accounts"] });
  };
}

export function useCommercialSummary() {
  return useQuery({ queryKey: ["commercial", "summary"], queryFn: () => apiGet<CommercialSummary>("/api/v1/commercial/summary/counts") });
}

export function useFacilities() {
  return useQuery({
    queryKey: ["commercial", "facilities"],
    queryFn: () => apiGet<Page<Facility>>(`/api/v1/commercial/facilities${query({ limit: 25 })}`),
  });
}

export function useReviews() {
  return useQuery({ queryKey: ["commercial", "reviews"], queryFn: () => apiGet<FacilityReview[]>("/api/v1/commercial/reviews") });
}

export function useCovenantTests(facilityId: string | null) {
  return useQuery({
    queryKey: ["commercial", "tests", facilityId],
    queryFn: () => apiGet<CovenantTest[]>(`/api/v1/commercial/facilities/${facilityId}/tests`),
    enabled: facilityId !== null,
  });
}

export interface Proposal {
  customer_number: string;
  account_number: string;
  facility_type: string;
  credit_limit: number;
  term_months: number;
  purpose: string;
}

export function useProposeFacility() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (body: Proposal) => apiPost<Facility>("/api/v1/commercial/facilities", body), onSuccess: invalidate });
}

export function useFacilityAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action, amount }: { id: string; action: "approve" | "committee" | "decline" | "draw" | "repay" | "reviews"; amount?: number }) =>
      apiPost<Facility>(`/api/v1/commercial/facilities/${id}/${action}`, amount !== undefined ? { amount } : {}),
    onSuccess: invalidate,
  });
}

export function useSubmitFigures() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; period_end: string; ebitda: number; debt_service: number; total_debt: number }) =>
      apiPost<CovenantTest>(`/api/v1/commercial/facilities/${id}/tests`, body),
    onSuccess: invalidate,
  });
}

export function useWaiveBreach() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (testId: string) => apiPost<Facility>(`/api/v1/commercial/tests/${testId}/waive`, {}), onSuccess: invalidate });
}

export function useDecideReview() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, renew }: { id: string; renew: boolean }) => apiPost<FacilityReview>(`/api/v1/commercial/reviews/${id}/decide`, { renew }),
    onSuccess: invalidate,
  });
}
