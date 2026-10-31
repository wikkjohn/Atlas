import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import { accountCurrency } from "@/services/commercial";
import { toMinorUnits } from "@/services/format";
import type { Page } from "@/types/enterprise";
import type { TradeDemand, TradeInstrument, TradeSummary } from "@/types/trade";

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["trade"] });
    void client.invalidateQueries({ queryKey: ["accounts"] });
  };
}

export function useTradeSummary() {
  return useQuery({ queryKey: ["trade", "summary"], queryFn: () => apiGet<TradeSummary>("/api/v1/trade/summary/counts") });
}

export const INSTRUMENTS_PAGE = 25;

/** A page of instruments, newest first; `offset` pages back through older ones. */
export function useInstruments(offset = 0) {
  return useQuery({
    queryKey: ["trade", "instruments", offset],
    queryFn: () => apiGet<Page<TradeInstrument>>(`/api/v1/trade/instruments${query({ limit: INSTRUMENTS_PAGE, offset })}`),
    placeholderData: keepPreviousData, // the page stays while the next one loads
  });
}

export function useDemands(instrumentId: string | null) {
  return useQuery({
    queryKey: ["trade", "demands", instrumentId],
    queryFn: () => apiGet<TradeDemand[]>(`/api/v1/trade/instruments/${instrumentId}/demands`),
    enabled: instrumentId !== null,
  });
}

export interface InstrumentRequest {
  kind: string;
  customer_number: string;
  account_number: string;
  beneficiary_name: string;
  beneficiary_country: string;
  /** In major units of the account's currency: converted once the account is found. */
  amount_major: number;
  expires_on: string;
  purpose: string;
}

export function useRequestInstrument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ amount_major, ...body }: InstrumentRequest) => {
      const currency = await accountCurrency(body.account_number);
      return apiPost<TradeInstrument>("/api/v1/trade/instruments", { ...body, amount: toMinorUnits(amount_major, currency) });
    },
    onSuccess: invalidate,
  });
}

export function useInstrumentAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "committee" | "decline" | "expire" }) =>
      apiPost<TradeInstrument>(`/api/v1/trade/instruments/${id}/${action}`, {}),
    onSuccess: invalidate,
  });
}

export function useReceiveDemand() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; amount: number; presented_on: string; discrepancies: string[] }) =>
      apiPost<TradeDemand>(`/api/v1/trade/instruments/${id}/demands`, body),
    onSuccess: invalidate,
  });
}

export function useDecideDemand() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, pay, note }: { id: string; pay: boolean; note?: string }) =>
      apiPost<TradeDemand>(`/api/v1/trade/demands/${id}/${pay ? "pay" : "reject"}`, pay ? {} : { note: note ?? "Not honoured" }),
    onSuccess: invalidate,
  });
}
