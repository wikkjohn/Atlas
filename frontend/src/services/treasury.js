import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut, query } from "@/services/api";
import { toMinorUnits } from "@/services/format";
function useInvalidate() {
    const client = useQueryClient();
    return () => void client.invalidateQueries({ queryKey: ["treasury"] });
}
export function useTreasurySummary() {
    return useQuery({ queryKey: ["treasury", "summary"], queryFn: () => apiGet("/api/v1/treasury/summary/counts") });
}
export function useCounterparties() {
    return useQuery({ queryKey: ["treasury", "counterparties"], queryFn: () => apiGet("/api/v1/treasury/counterparties") });
}
export const TREASURY_PAGE = 25;
/** A page of deals, newest first; `offset` pages back through older ones. */
export function useDeals(offset = 0) {
    return useQuery({
        queryKey: ["treasury", "deals", offset],
        queryFn: () => apiGet(`/api/v1/treasury/deals${query({ limit: TREASURY_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    });
}
export function useLiquidity() {
    return useQuery({ queryKey: ["treasury", "liquidity"], queryFn: () => apiGet("/api/v1/treasury/liquidity") });
}
export function useFxDesk() {
    return useQuery({ queryKey: ["treasury", "fx-desk"], queryFn: () => apiGet("/api/v1/treasury/fx-desk") });
}
export function useFxTrades(offset = 0) {
    return useQuery({
        queryKey: ["treasury", "fx-trades", offset],
        queryFn: () => apiGet(`/api/v1/treasury/fx-trades${query({ limit: TREASURY_PAGE, offset })}`),
        placeholderData: keepPreviousData,
    });
}
export function useBookDeal() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ principal_major, rate_percent, ...body }) => apiPost("/api/v1/treasury/deals", {
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
        mutationFn: ({ id, action }) => apiPost(`/api/v1/treasury/deals/${id}/${action}`, {}),
        onSuccess: invalidate,
    });
}
export function useSetCounterpartyLimit() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ code, limit_usd }) => apiPut(`/api/v1/treasury/counterparties/${code}/limit`, { limit_usd }),
        onSuccess: invalidate,
    });
}
export function useBookFxTrade() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ sell_major, ...body }) => apiPost("/api/v1/treasury/fx-trades", {
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
        mutationFn: ({ id, action }) => apiPost(`/api/v1/treasury/fx-trades/${id}/${action}`, {}),
        onSuccess: invalidate,
    });
}
