import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { ServiceCase, ServiceSummary } from "@/types/customerService";
import type { Page } from "@/types/enterprise";

export const SERVICE_PAGE = 25;
const BASE = "/api/v1/customer-service";

function useInvalidate() {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: ["customer-service"] });
}

export function useServiceSummary() {
  return useQuery({ queryKey: ["customer-service", "summary"], queryFn: () => apiGet<ServiceSummary>(`${BASE}/summary/counts`) });
}

/** A page of cases, most urgent first; `status` is "unresolved" or a status. */
export function useCases(offset = 0, status = "unresolved") {
  return useQuery({
    queryKey: ["customer-service", "cases", offset, status],
    queryFn: () => apiGet<Page<ServiceCase>>(`${BASE}/cases${query({ limit: SERVICE_PAGE, offset, status: status || undefined })}`),
    placeholderData: keepPreviousData,
  });
}

export interface OpenCase {
  customer_number: string;
  account_number?: string;
  category: string;
  channel: string;
  topic: string;
  priority: string;
  subject: string;
  description: string;
}

export function useOpenCase() {
  const invalidate = useInvalidate();
  return useMutation({ mutationFn: (body: OpenCase) => apiPost<ServiceCase>(`${BASE}/cases`, body), onSuccess: invalidate });
}

type Action = "respond" | "await-customer" | "resume" | "redress/pay" | "redress/withdraw";

export function useCaseAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action, message }: { id: string; action: Action; message?: string }) =>
      apiPost<ServiceCase>(`${BASE}/cases/${id}/${action}`, action === "respond" ? { message: message ?? "Thank you, we are looking into this." } : {}),
    onSuccess: invalidate,
  });
}

export function useProposeRedress() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, amount, account_number }: { id: string; amount: number; account_number: string }) =>
      apiPost<ServiceCase>(`${BASE}/cases/${id}/redress`, { amount, account_number }),
    onSuccess: invalidate,
  });
}

export function useResolveCase() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, resolution, outcome }: { id: string; resolution: string; outcome?: string }) =>
      apiPost<ServiceCase>(`${BASE}/cases/${id}/resolve`, { resolution, outcome }),
    onSuccess: invalidate,
  });
}

export function useSweep() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => apiPost<{ checked: number; response_breached: number; resolution_breached: number }>(`${BASE}/sweep`, {}),
    onSuccess: invalidate,
  });
}
