import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPost, query } from "@/services/api";
import { accountCurrency } from "@/services/commercial";
import { toMinorUnits } from "@/services/format";
import type { Page } from "@/types/enterprise";
import type { BulkFile, ClearingBatch, OutgoingPayment, PaymentOpsSummary, Recall } from "@/types/paymentOps";

export const OPS_PAGE = 25;

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["payment-ops"] });
    void client.invalidateQueries({ queryKey: ["accounts"] });
  };
}

export function usePaymentOpsSummary() {
  return useQuery({ queryKey: ["payment-ops", "summary"], queryFn: () => apiGet<PaymentOpsSummary>("/api/v1/payment-ops/summary/counts") });
}

export function useBanks() {
  return useQuery({ queryKey: ["payment-ops", "banks"], queryFn: () => apiGet<{ code: string; name: string }[]>("/api/v1/payment-ops/banks") });
}

/** A page of outgoing payments, newest first. */
export function useOutgoing(offset = 0) {
  return useQuery({
    queryKey: ["payment-ops", "payments", offset],
    queryFn: () => apiGet<Page<OutgoingPayment>>(`/api/v1/payment-ops/payments${query({ limit: OPS_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  });
}

export function useBatches() {
  return useQuery({ queryKey: ["payment-ops", "batches"], queryFn: () => apiGet<Page<ClearingBatch>>(`/api/v1/payment-ops/batches${query({ limit: 10 })}`) });
}

export function useBulkFiles(offset = 0) {
  return useQuery({
    queryKey: ["payment-ops", "bulk", offset],
    queryFn: () => apiGet<Page<BulkFile>>(`/api/v1/payment-ops/bulk${query({ limit: OPS_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  });
}

export function useRecalls(offset = 0) {
  return useQuery({
    queryKey: ["payment-ops", "recalls", offset],
    queryFn: () => apiGet<Page<Recall>>(`/api/v1/payment-ops/recalls${query({ limit: OPS_PAGE, offset })}`),
    placeholderData: keepPreviousData,
  });
}

export interface OutgoingRequest {
  account_number: string;
  beneficiary_name: string;
  beneficiary_bank: string;
  beneficiary_account: string;
  /** In major units of the account's currency. */
  amount_major: number;
  reference: string;
}

export function useCreateOutgoing() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ amount_major, ...body }: OutgoingRequest) => {
      const currency = await accountCurrency(body.account_number);
      return apiPost<OutgoingPayment>("/api/v1/payment-ops/payments", { ...body, amount: toMinorUnits(amount_major, currency) });
    },
    onSuccess: invalidate,
  });
}

export function useDecideOutgoing() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      apiPost<OutgoingPayment>(`/api/v1/payment-ops/payments/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Not approved" }),
    onSuccess: invalidate,
  });
}

export function useRunCycle() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (currency: string) => apiPost<{ batch: ClearingBatch | null }>("/api/v1/payment-ops/cycles", { currency: currency.toUpperCase() }),
    onSuccess: invalidate,
  });
}

/** Lines as typed: `name, bank, account, amount, reference`, the amount in major units. */
export function parseBulkLines(text: string, currency: string) {
  return text
    .split("\n")
    .map((row) => row.trim())
    .filter(Boolean)
    .map((row) => {
      const [name = "", bank = "", account = "", amount = "", reference = ""] = row.split(",").map((cell) => cell.trim());
      const major = Number(amount);
      return { name, bank: bank.toUpperCase(), account, amount: Number.isFinite(major) && amount !== "" ? toMinorUnits(major, currency) : null, reference };
    });
}

export function useReceiveBulk() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ account_number, file_name, text }: { account_number: string; file_name: string; text: string }) => {
      const currency = await accountCurrency(account_number);
      return apiPost<BulkFile>("/api/v1/payment-ops/bulk", { account_number, file_name, lines: parseBulkLines(text, currency) });
    },
    onSuccess: invalidate,
  });
}

export function useDecideBulk() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, release }: { id: string; release: boolean }) =>
      apiPost<BulkFile>(`/api/v1/payment-ops/bulk/${id}/${release ? "release" : "reject"}`, release ? {} : { note: "File not released" }),
    onSuccess: invalidate,
  });
}

export function useRequestRecall() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { payment_number: string; reason_code: string }) => apiPost<Recall>("/api/v1/payment-ops/recalls", body),
    onSuccess: invalidate,
  });
}

export function useRecallAction() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "withdraw" | "resolve" }) => apiPost<Recall>(`/api/v1/payment-ops/recalls/${id}/${action}`, {}),
    onSuccess: invalidate,
  });
}
