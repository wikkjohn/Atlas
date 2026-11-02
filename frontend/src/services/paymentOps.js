import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
import { accountCurrency } from "@/services/commercial";
import { toMinorUnits } from "@/services/format";
export const OPS_PAGE = 25;
function useInvalidate() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["payment-ops"] });
        void client.invalidateQueries({ queryKey: ["accounts"] });
    };
}
export function usePaymentOpsSummary() {
    return useQuery({ queryKey: ["payment-ops", "summary"], queryFn: () => apiGet("/api/v1/payment-ops/summary/counts") });
}
export function useBanks() {
    return useQuery({ queryKey: ["payment-ops", "banks"], queryFn: () => apiGet("/api/v1/payment-ops/banks") });
}
/** A page of outgoing payments, newest first. */
export function useOutgoing(offset = 0) {
    return useQuery({
        queryKey: ["payment-ops", "payments", offset],
        queryFn: () => apiGet(`/api/v1/payment-ops/payments${query({ limit: OPS_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    });
}
export function useBatches() {
    return useQuery({ queryKey: ["payment-ops", "batches"], queryFn: () => apiGet(`/api/v1/payment-ops/batches${query({ limit: 10 })}`) });
}
export function useBulkFiles(offset = 0) {
    return useQuery({
        queryKey: ["payment-ops", "bulk", offset],
        queryFn: () => apiGet(`/api/v1/payment-ops/bulk${query({ limit: OPS_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    });
}
export function useRecalls(offset = 0) {
    return useQuery({
        queryKey: ["payment-ops", "recalls", offset],
        queryFn: () => apiGet(`/api/v1/payment-ops/recalls${query({ limit: OPS_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    });
}
export function useCreateOutgoing() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: async ({ amount_major, ...body }) => {
            const currency = await accountCurrency(body.account_number);
            return apiPost("/api/v1/payment-ops/payments", { ...body, amount: toMinorUnits(amount_major, currency) });
        },
        onSuccess: invalidate,
    });
}
export function useDecideOutgoing() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, approve }) => apiPost(`/api/v1/payment-ops/payments/${id}/${approve ? "approve" : "reject"}`, approve ? {} : { note: "Not approved" }),
        onSuccess: invalidate,
    });
}
export function useRunCycle() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (currency) => apiPost("/api/v1/payment-ops/cycles", { currency: currency.toUpperCase() }),
        onSuccess: invalidate,
    });
}
/** Lines as typed: `name, bank, account, amount, reference`, the amount in major units. */
export function parseBulkLines(text, currency) {
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
        mutationFn: async ({ account_number, file_name, text }) => {
            const currency = await accountCurrency(account_number);
            return apiPost("/api/v1/payment-ops/bulk", { account_number, file_name, lines: parseBulkLines(text, currency) });
        },
        onSuccess: invalidate,
    });
}
export function useDecideBulk() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, release }) => apiPost(`/api/v1/payment-ops/bulk/${id}/${release ? "release" : "reject"}`, release ? {} : { note: "File not released" }),
        onSuccess: invalidate,
    });
}
export function useRequestRecall() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/payment-ops/recalls", body),
        onSuccess: invalidate,
    });
}
export function useRecallAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action }) => apiPost(`/api/v1/payment-ops/recalls/${id}/${action}`, {}),
        onSuccess: invalidate,
    });
}
