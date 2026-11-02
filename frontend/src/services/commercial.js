import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, query } from "@/services/api";
import { toMinorUnits } from "@/services/format";
function useInvalidate() {
    const client = useQueryClient();
    return () => {
        void client.invalidateQueries({ queryKey: ["commercial"] });
        void client.invalidateQueries({ queryKey: ["accounts"] });
    };
}
export function useCommercialSummary() {
    return useQuery({ queryKey: ["commercial", "summary"], queryFn: () => apiGet("/api/v1/commercial/summary/counts") });
}
export function useFacilities() {
    return useQuery({
        queryKey: ["commercial", "facilities"],
        queryFn: () => apiGet(`/api/v1/commercial/facilities${query({ limit: 25 })}`),
    });
}
export function useReviews() {
    return useQuery({ queryKey: ["commercial", "reviews"], queryFn: () => apiGet("/api/v1/commercial/reviews") });
}
export function useCovenantTests(facilityId) {
    return useQuery({
        queryKey: ["commercial", "tests", facilityId],
        queryFn: () => apiGet(`/api/v1/commercial/facilities/${facilityId}/tests`),
        enabled: facilityId !== null,
    });
}
/** The currency of an account, looked up by its number. */
export async function accountCurrency(number) {
    const wanted = number.trim().toUpperCase();
    const found = await apiGet(`/api/v1/accounts${query({ q: wanted, limit: 5 })}`);
    const account = found.items.find((a) => a.account_number.toUpperCase() === wanted);
    if (!account)
        throw new Error(`No account ${number}.`);
    return account.currency;
}
export function useProposeFacility() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: async ({ credit_limit_major, ...body }) => {
            const currency = await accountCurrency(body.account_number);
            return apiPost("/api/v1/commercial/facilities", { ...body, credit_limit: toMinorUnits(credit_limit_major, currency) });
        },
        onSuccess: invalidate,
    });
}
export function useFacilityAction() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, action, amount }) => apiPost(`/api/v1/commercial/facilities/${id}/${action}`, amount !== undefined ? { amount } : {}),
        onSuccess: invalidate,
    });
}
export function useSubmitFigures() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, ...body }) => apiPost(`/api/v1/commercial/facilities/${id}/tests`, body),
        onSuccess: invalidate,
    });
}
export function useWaiveBreach() {
    const invalidate = useInvalidate();
    return useMutation({ mutationFn: (testId) => apiPost(`/api/v1/commercial/tests/${testId}/waive`, {}), onSuccess: invalidate });
}
export function useDecideReview() {
    const invalidate = useInvalidate();
    return useMutation({
        mutationFn: ({ id, renew }) => apiPost(`/api/v1/commercial/reviews/${id}/decide`, { renew }),
        onSuccess: invalidate,
    });
}
