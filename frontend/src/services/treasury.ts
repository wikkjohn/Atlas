import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, apiPut, query } from "@/services/api";
import { toMinorUnits } from "@/services/format";
import type { Page } from "@/types/enterprise";
import type { Counterparty, Deal, FxDesk, FxTrade, Liquidity, TreasurySummary } from "@/types/treasury";

function useInvalidate() {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: ["treasury"] });
}

export function useTreasurySummary() {
  return useQuery({ queryKey: ["treasury", "summary"], queryFn: () => apiGet<TreasurySummary>("/api/v1/treasury/summary/counts") });
}

export function useCounterparties() {
  return useQuery({ queryKey: ["treasury", "counterparties"], queryFn: () => apiGet<Counterparty[]>("/api/v1/treasury/counterparties") });
}

export function useDeals() {
  return useQuery({ queryKey: ["treasury", "deals"], queryFn: () => apiGet<Page<Deal>>(`/api/v1/treasury/deals${query({ limit: 25 })}`) });
}

export function useLiquidity() {
  return useQuery({ queryKey: ["treasury", "liquidity"], queryFn: () => apiGet<Liquidity>("/api/v1/treasury/liquidity") });
}

export function useFxDesk() {
  return useQuery({ queryKey: ["treasury", "fx-desk"], queryFn: () => apiGet<FxDesk>("/api/v1/treasury/fx-desk") });
}

export function useFxTrades() {
  return useQuery({ queryKey: ["treasury", "fx-trades"], queryFn: () => apiGet<Page<FxTrade>>(`/api/v1/treasury/fx-trades${query({ limit: 25 })}`) });
}

export interface DealRequest {
  kind: string;
  counterparty_code: string;
  currency: string;
  /** In major units of the deal's currency. */
  principal_major: number;
  rate_percent: number;
  tenor_days: number;
}

export function useBookDeal() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ principal_major, rate_percent, ...body }: DealRequest) =>
      apiPost<Deal>("/api/v1/treasury/deals", {
        ...body,
        currency: body.currency.toUpperCase(),
        principal: toMinorUnits(principal_major, body.currency.toUpperCase()),
        rate_bps: Math.round(rate_percent * 100),
      }),
    onSuccess: invalidate,
  });
}

export function useDealAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "confirm" | "cancel" | "mature" }) => apiPost<Deal>(`/api/v1/treasury/deals/${id}/${action}`, {}),
    onSuccess: invalidate,
  });
}

export function useSetCounterpartyLimit() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ code, limit_usd }: { code: string; limit_usd: number }) => apiPut<Counterparty>(`/api/v1/treasury/counterparties/${code}/limit`, { limit_usd }),
    onSuccess: invalidate,
  });
}

export interface FxTradeRequest {
  counterparty_code: string;
  sell_currency: string;
  buy_currency: string;
  /** In major units of the sold currency. */
  sell_major: number;
}

export function useBookFxTrade() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ sell_major, ...body }: FxTradeRequest) =>
      apiPost<FxTrade>("/api/v1/treasury/fx-trades", {
        counterparty_code: body.counterparty_code,
        sell_currency: body.sell_currency.toUpperCase(),
        buy_currency: body.buy_currency.toUpperCase(),
        sell_amount: toMinorUnits(sell_major, body.sell_currency.toUpperCase()),
      }),
    onSuccess: invalidate,
  });
}

export function useFxTradeAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "confirm" | "cancel" }) => apiPost<FxTrade>(`/api/v1/treasury/fx-trades/${id}/${action}`, {}),
    onSuccess: invalidate,
  });
}
