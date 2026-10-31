import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import { toMinorUnits } from "@/services/format";
import type { Page } from "@/types/enterprise";
import type {
  MortgageApplication,
  MortgageOffer,
  MortgageProduct,
  MortgageSummary,
  Property,
  Quote,
  Valuation,
} from "@/types/mortgages";

function useInvalidateMortgages() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["mortgages"] });
    void client.invalidateQueries({ queryKey: ["loans"] });
    void client.invalidateQueries({ queryKey: ["accounts"] });
  };
}

export function useMortgageSummary() {
  return useQuery({ queryKey: ["mortgages", "summary"], queryFn: () => apiGet<MortgageSummary>("/api/v1/mortgages/summary/counts") });
}

export function useMortgageProducts() {
  return useQuery({ queryKey: ["mortgages", "products"], queryFn: () => apiGet<MortgageProduct[]>("/api/v1/mortgages/products") });
}

export function useProperties() {
  return useQuery({
    queryKey: ["mortgages", "properties"],
    queryFn: () => apiGet<Page<Property>>(`/api/v1/mortgages/properties${query({ limit: 25 })}`),
  });
}

export function useOffers() {
  return useQuery({
    queryKey: ["mortgages", "offers"],
    queryFn: () => apiGet<Page<MortgageOffer>>(`/api/v1/mortgages/offers${query({ limit: 25 })}`),
  });
}

/** The currency of a customer (their country's), looked up by customer number. */
export async function customerCurrency(number: string): Promise<string> {
  const found = await apiGet<Page<{ customer_number: string; currency: string }>>(`/api/v1/customers${query({ q: number, limit: 5 })}`);
  const customer = found.items.find((c) => c.customer_number === number);
  if (!customer) throw new Error(`No customer ${number}.`);
  return customer.currency;
}

export function useRegisterProperty() {
  const invalidate = useInvalidateMortgages();
  return useMutation({
    // The price is entered in major units of the customer's currency.
    mutationFn: async ({ purchase_price_major, ...body }: { customer_number: string; property_type: string; purchase_price_major: number }) => {
      const currency = await customerCurrency(body.customer_number);
      return apiPost<Property>("/api/v1/mortgages/properties", { ...body, purchase_price: toMinorUnits(purchase_price_major, currency) });
    },
    onSuccess: invalidate,
  });
}

export function useValueProperty() {
  const invalidate = useInvalidateMortgages();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; method: "desktop" | "surveyor"; value?: number }) =>
      apiPost<Valuation>(`/api/v1/mortgages/properties/${id}/valuations`, body),
    onSuccess: invalidate,
  });
}

export function useQuote() {
  return useMutation({ mutationFn: (body: MortgageApplication) => apiPost<Quote>("/api/v1/mortgages/quote", body) });
}

export function useRequestOffer() {
  const invalidate = useInvalidateMortgages();
  return useMutation({
    mutationFn: (body: MortgageApplication) => apiPost<MortgageOffer>("/api/v1/mortgages/offers", body),
    onSuccess: invalidate,
  });
}

export function useOfferAction() {
  const invalidate = useInvalidateMortgages();
  return useMutation({
    mutationFn: ({ id, action, approve }: { id: string; action: "decide" | "accept" | "complete" | "withdraw"; approve?: boolean }) =>
      apiPost<MortgageOffer>(`/api/v1/mortgages/offers/${id}/${action}`, action === "decide" ? { approve } : {}),
    onSuccess: invalidate,
  });
}
