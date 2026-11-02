import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost, query } from "@/services/api";
function useInvalidateJobs() {
    const client = useQueryClient();
    return () => {
        for (const key of ["jobs", "job-schedules"])
            void client.invalidateQueries({ queryKey: [key] });
    };
}
/** Jobs refresh while any is queued or running. */
export function useJobs(params) {
    return useQuery({
        queryKey: ["jobs", params],
        queryFn: () => apiGet(`/api/v1/jobs${query(params)}`),
        placeholderData: keepPreviousData,
        refetchInterval: (q) => q.state.data?.items.some((j) => j.status === "queued" || j.status === "running") ? 2000 : false,
    });
}
export function useJobSchedules() {
    return useQuery({
        queryKey: ["job-schedules"],
        queryFn: () => apiGet("/api/v1/job-schedules"),
    });
}
export function useUpdateSchedule() {
    const invalidate = useInvalidateJobs();
    return useMutation({
        mutationFn: ({ name, ...body }) => apiPatch(`/api/v1/job-schedules/${name}`, body),
        onSuccess: invalidate,
    });
}
export function useRunSchedule() {
    const invalidate = useInvalidateJobs();
    return useMutation({
        mutationFn: (name) => apiPost(`/api/v1/job-schedules/${name}/run`, {}),
        onSuccess: invalidate,
    });
}
/** One job, refreshed while it is queued or running. */
export function useJob(id) {
    return useQuery({
        queryKey: ["jobs", "detail", id],
        queryFn: () => apiGet(`/api/v1/jobs/${id}`),
        enabled: Boolean(id),
        refetchInterval: (q) => (q.state.data?.status === "queued" || q.state.data?.status === "running" ? 1500 : false),
    });
}
