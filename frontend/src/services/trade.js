import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
import { accountCurrency } from "@/services/commercial";
import { toMinorUnits } from "@/services/format";
function useInvalidate() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["trade"] });
        void client.invalidateQueries({ queryKey: ["accounts"] });
    };
}
export function useTradeSummary() {
    return useQuery({ queryKey: ["trade", "summary"], queryFn: () => apiGet("/api/v1/trade/summary/counts") });
}
export const INSTRUMENTS_PAGE = 25;
/** A page of instruments, newest first; `offset` pages back through older ones. */
export function useInstruments(offset = 0) {
    return useQuery({
        queryKey: ["trade", "instruments", offset],
        queryFn: () => apiGet(`/api/v1/trade/instruments${query({ limit: INSTRUMENTS_PAGE, offset })}`),
        placeholderData: keepPreviousData, // the page stays while the next one loads
    });
}
export function useDemands(instrumentId) {
    return useQuery({
        queryKey: ["trade", "demands", instrumentId],
        queryFn: () => apiGet(`/api/v1/trade/instruments/${instrumentId}/demands`),
        enabled: instrumentId !== null,
    });
}
export function useRequestInstrument() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: async ({ amount_major, ...body }) => {
            const currency = await accountCurrency(body.account_number);
            return apiPost("/api/v1/trade/instruments", { ...body, amount: toMinorUnits(amount_major, currency) });
        },
        onSuccess: invalidate,
    });
}
export function useInstrumentAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action }) => apiPost(`/api/v1/trade/instruments/${id}/${action}`, {}),
        onSuccess: invalidate,
    });
}
export function useReceiveDemand() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, ...body }) => apiPost(`/api/v1/trade/instruments/${id}/demands`, body),
        onSuccess: invalidate,
    });
}
export function useDecideDemand() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, pay, note }) => apiPost(`/api/v1/trade/demands/${id}/${pay ? "pay" : "reject"}`, pay ? {} : { note: note ?? "Not honoured" }),
        onSuccess: invalidate,
    });
}
