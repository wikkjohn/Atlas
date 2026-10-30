import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { Job } from "@/types/jobs";
import type { MonthEndRun, RetailProduct, RetailSummary, StandingOrder, Statement, StatementDetail } from "@/types/retail";

function useInvalidateRetail() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["retail"] });
    void client.invalidateQueries({ queryKey: ["accounts"] });
  };
}

export function useRetailSummary() {
  return useQuery({ queryKey: ["retail", "summary"], queryFn: () => apiGet<RetailSummary>("/api/v1/retail/summary") });
}

export function useRetailProducts() {
  return useQuery({ queryKey: ["retail", "products"], queryFn: () => apiGet<RetailProduct[]>("/api/v1/retail/products") });
}

export function useUpdateProduct() {
  const invalidate = useInvalidateRetail();
  return useMutation({
    mutationFn: ({ account_type, ...body }: Partial<RetailProduct> & { account_type: string }) =>
      apiPatch<RetailProduct>(`/api/v1/retail/products/${account_type}`, body),
    onSuccess: invalidate,
  });
}

export function useStandingOrders(status?: string) {
  return useQuery({
    queryKey: ["retail", "standing-orders", status],
    queryFn: () => apiGet<Page<StandingOrder>>(`/api/v1/retail/standing-orders${query({ status, limit: 25 })}`),
  });
}

export function useCreateStandingOrder() {
  const invalidate = useInvalidateRetail();
  return useMutation({
    mutationFn: (body: {
      debtor_account_number: string;
      creditor_account_number: string;
      amount: number;
      frequency: "weekly" | "monthly";
      first_date: string;
      reference: string;
    }) => apiPost<StandingOrder>("/api/v1/retail/standing-orders", body),
    onSuccess: invalidate,
  });
}

export function useCancelStandingOrder() {
  const invalidate = useInvalidateRetail();
  return useMutation({
    mutationFn: (id: string) => apiPost<StandingOrder>(`/api/v1/retail/standing-orders/${id}/cancel`, {}),
    onSuccess: invalidate,
  });
}

export function useStatements() {
  return useQuery({
    queryKey: ["retail", "statements"],
    queryFn: () => apiGet<Page<Statement>>(`/api/v1/retail/statements${query({ limit: 15 })}`),
  });
}

export function useStatement(id: string | null) {
  return useQuery({
    queryKey: ["retail", "statement", id],
    queryFn: () => apiGet<StatementDetail>(`/api/v1/retail/statements/${id}`),
    enabled: Boolean(id),
  });
}

export function useMonthEnds() {
  return useQuery({ queryKey: ["retail", "month-ends"], queryFn: () => apiGet<MonthEndRun[]>("/api/v1/retail/month-ends") });
}

export function useRunMonthEnd() {
  const invalidate = useInvalidateRetail();
  return useMutation({
    mutationFn: (period: string | null) => apiPost<Job>("/api/v1/retail/month-ends", period ? { period } : {}),
    onSuccess: invalidate,
  });
}
