import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import { toMinorUnits } from "@/services/format";
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
  /** In major units of the account's currency: converted once the account is found. */
  credit_limit_major: number;
  term_months: number;
  purpose: string;
}

/** The currency of an account, looked up by its number. */
export async function accountCurrency(number: string): Promise<string> {
  const found = await apiGet<Page<{ account_number: string; currency: string }>>(`/api/v1/accounts${query({ q: number, limit: 5 })}`);
  const account = found.items.find((a) => a.account_number === number);
  if (!account) throw new Error(`No account ${number}.`);
  return account.currency;
}

export function useProposeFacility() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ credit_limit_major, ...body }: Proposal) => {
      const currency = await accountCurrency(body.account_number);
      return apiPost<Facility>("/api/v1/commercial/facilities", { ...body, credit_limit: toMinorUnits(credit_limit_major, currency) });
    },
    onSuccess: invalidate,
  });
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
