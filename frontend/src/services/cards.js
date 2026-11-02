import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
function useInvalidateCards() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["cards"] });
        void client.invalidateQueries({ queryKey: ["accounts"] });
    };
}
export function useCardSummary() {
    return useQuery({ queryKey: ["cards", "summary"], queryFn: () => apiGet("/api/v1/cards/summary/counts") });
}
export function useCardProducts() {
    return useQuery({ queryKey: ["cards", "products"], queryFn: () => apiGet("/api/v1/cards/products") });
}
export function useCards() {
    return useQuery({ queryKey: ["cards", "list"], queryFn: () => apiGet(`/api/v1/cards${query({ limit: 25 })}`) });
}
export function useAuthorizations() {
    return useQuery({
        queryKey: ["cards", "authorizations"],
        queryFn: () => apiGet(`/api/v1/cards/authorizations/list${query({ limit: 20 })}`),
    });
}
export function useDisputes() {
    return useQuery({
        queryKey: ["cards", "disputes"],
        queryFn: () => apiGet(`/api/v1/cards/disputes/list${query({ limit: 20 })}`),
    });
}
export function useIssueCard() {
    const invalidate = useInvalidateCards();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/cards", body),
        onSuccess: invalidate,
    });
}
export function useCardAction() {
    const invalidate = useInvalidateCards();
    return useMutation({
        mutationFn: ({ id, action, reason }) => apiPost(`/api/v1/cards/${id}/${action}`, reason ? { reason } : {}),
        onSuccess: invalidate,
    });
}
export function useAuthorize() {
    const invalidate = useInvalidateCards();
    return useMutation({
        mutationFn: ({ cardId, ...body }) => apiPost(`/api/v1/cards/${cardId}/authorizations`, body),
        onSuccess: invalidate,
    });
}
export function useOpenDispute() {
    const invalidate = useInvalidateCards();
    return useMutation({
        mutationFn: (body) => apiPost("/api/v1/cards/disputes", body),
        onSuccess: invalidate,
    });
}
export function useDecideDispute() {
    const invalidate = useInvalidateCards();
    return useMutation({
        mutationFn: ({ id, refund }) => apiPost(`/api/v1/cards/disputes/${id}/decide`, { refund }),
        onSuccess: invalidate,
    });
}
