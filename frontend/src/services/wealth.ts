import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { IncomeDistribution, InvestmentOrder, InvestmentProfile, Portfolio, Security, Valuation, WealthSummary } from "@/types/wealth";

export const WEALTH_PAGE = 25;

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["wealth"] });
    void client.invalidateQueries({ queryKey: ["accounts"] });
  };
}

export function useWealthSummary() {
  return useQuery({ queryKey: ["wealth", "summary"], queryFn: () => apiGet<WealthSummary>("/api/v1/wealth/summary/counts") });
}

export function useSecurities() {
  return useQuery({ queryKey: ["wealth", "securities"], queryFn: () => apiGet<Security[]>("/api/v1/wealth/securities") });
}

/** A page of portfolios, newest first. */
export function usePortfolios(offset = 0) {
  return useQuery({
    queryKey: ["wealth", "portfolios", offset],
    queryFn: () => apiGet<Page<Portfolio>>(`/api/v1/wealth/portfolios${query({ limit: WEALTH_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  });
}

export function useValuation(portfolioNumber: string | null) {
  return useQuery({
    queryKey: ["wealth", "valuation", portfolioNumber],
    queryFn: () => apiGet<Valuation>(`/api/v1/wealth/portfolios/${portfolioNumber}/valuation`),
    enabled: Boolean(portfolioNumber),
  });
}

/** A page of orders, newest first. */
export function useOrders(offset = 0) {
  return useQuery({
    queryKey: ["wealth", "orders", offset],
    queryFn: () => apiGet<Page<InvestmentOrder>>(`/api/v1/wealth/orders${query({ limit: WEALTH_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  });
}

export function useDistributions() {
  return useQuery({
    queryKey: ["wealth", "distributions"],
    queryFn: () => apiGet<Page<IncomeDistribution>>(`/api/v1/wealth/distributions${query({ limit: 10 })}`),
  });
}

export interface ProfileRequest {
  customer_number: string;
  objective: InvestmentProfile["objective"];
  horizon_years: number;
  knowledge: InvestmentProfile["knowledge"];
  loss_capacity: InvestmentProfile["loss_capacity"];
}

export function useRecordProfile() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: ProfileRequest) => apiPost<InvestmentProfile>("/api/v1/wealth/profiles", body),
    onSuccess: invalidate,
  });
}

export function useOpenPortfolio() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (account_number: string) => apiPost<Portfolio>("/api/v1/wealth/portfolios", { account_number }),
    onSuccess: invalidate,
  });
}

export function useClosePortfolio() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (portfolioNumber: string) => apiPost<Portfolio>(`/api/v1/wealth/portfolios/${portfolioNumber}/close`, {}),
    onSuccess: invalidate,
  });
}

export interface OrderRequest {
  portfolio_number: string;
  security_code: string;
  side: "buy" | "sell";
  units: number;
}

export function usePlaceOrder() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: OrderRequest) => apiPost<InvestmentOrder>("/api/v1/wealth/orders", body),
    onSuccess: invalidate,
  });
}

export function useOrderAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" | "release" }) =>
      apiPost<InvestmentOrder>(
        `/api/v1/wealth/orders/${id}/${action}`,
        action === "approve" ? { note: "Insistent client" } : action === "reject" ? { note: "Unsuitable for the customer" } : {},
      ),
    onSuccess: invalidate,
  });
}

export function useDistribute() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (security_code: string) => apiPost<IncomeDistribution>("/api/v1/wealth/distributions", { security_code }),
    onSuccess: invalidate,
  });
}
