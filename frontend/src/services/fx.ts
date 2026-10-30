import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { FxDeal, FxPositions, FxQuote, FxRate, FxRevaluation } from "@/types/fx";

export const useFxRates = (on: string) =>
  useQuery({
    queryKey: ["fx", "rates", on],
    queryFn: () => apiGet<FxRate[]>(`/api/v1/fx/rates${query({ on })}`),
  });

export const useFxQuote = () =>
  useMutation({
    mutationFn: (body: { sell_currency: string; buy_currency: string; sell_amount: number; rate_date?: string }) =>
      apiPost<FxQuote>("/api/v1/fx/quote", body),
  });

export const useFxPositions = (asOf: string, enabled = true) =>
  useQuery({
    queryKey: ["fx", "positions", asOf],
    queryFn: () => apiGet<FxPositions>(`/api/v1/fx/positions${query({ as_of: asOf })}`),
    enabled,
  });

export const useFxRevaluations = (enabled = true) =>
  useQuery({
    queryKey: ["fx", "revaluations"],
    queryFn: () => apiGet<Page<FxRevaluation>>(`/api/v1/fx/revaluations${query({ limit: 10 })}`),
    enabled,
  });

export const useFxDeals = (enabled = true) =>
  useQuery({
    queryKey: ["fx", "deals"],
    queryFn: () => apiGet<Page<FxDeal>>(`/api/v1/fx/deals${query({ limit: 15 })}`),
    enabled,
  });

export function useRevalue() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (asOf: string) => apiPost<FxRevaluation>("/api/v1/fx/revaluations", { as_of: asOf }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["fx"] }),
  });
}
