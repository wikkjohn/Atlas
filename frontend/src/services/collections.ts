import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { ArrearsRow, CollectionsSummary, PaymentPlan, Recovery, WrittenOffRow } from "@/types/collections";
import type { Page } from "@/types/enterprise";

const BASE = "/api/v1/collections";

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["collections"] });
    void client.invalidateQueries({ queryKey: ["loans"] });
  };
}

export const useCollectionsSummary = () =>
  useQuery({ queryKey: ["collections", "summary"], queryFn: () => apiGet<CollectionsSummary>(`${BASE}/summary/counts`) });
export const useArrears = () => useQuery({ queryKey: ["collections", "arrears"], queryFn: () => apiGet<ArrearsRow[]>(`${BASE}/arrears`) });
export const usePlans = () => useQuery({ queryKey: ["collections", "plans"], queryFn: () => apiGet<Page<PaymentPlan>>(`${BASE}/plans${query({ limit: 25 })}`) });
export const useWrittenOff = () => useQuery({ queryKey: ["collections", "written-off"], queryFn: () => apiGet<WrittenOffRow[]>(`${BASE}/written-off`) });
export const useRecoveries = () => useQuery({ queryKey: ["collections", "recoveries"], queryFn: () => apiGet<Page<Recovery>>(`${BASE}/recoveries${query({ limit: 25 })}`) });

export function useProposePlan() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { loan_number: string; interval_days: number }) => apiPost<PaymentPlan>(`${BASE}/plans`, body),
    onSuccess: invalidate,
  });
}

export function useDecidePlan() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => apiPost<PaymentPlan>(`${BASE}/plans/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
    onSuccess: invalidate,
  });
}

export function useCollect() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => apiPost<{ as_of: string; plans: number; paid: number; missed: number; completed: number; broken: number }>(`${BASE}/plans/collect`, {}),
    onSuccess: invalidate,
  });
}

export function useRecordRecovery() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { loan_number: string; kind: string; amount: number }) => apiPost<Recovery>(`${BASE}/recoveries`, body),
    onSuccess: invalidate,
  });
}

export function useDecideRecovery() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => apiPost<Recovery>(`${BASE}/recoveries/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Rejected on review" }),
    onSuccess: invalidate,
  });
}
