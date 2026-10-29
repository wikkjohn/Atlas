import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch, apiPost, query } from "@/services/api";
import type { Page } from "@/types/enterprise";
import type { Job, JobSchedule } from "@/types/jobs";

type Params = Record<string, string | number | boolean | null | undefined>;

function useInvalidateJobs() {
  const client = useQueryClient();
  return () => {
    for (const key of ["jobs", "job-schedules"]) void client.invalidateQueries({ queryKey: [key] });
  };
}

/** Jobs refresh while any is queued or running. */
export function useJobs(params: Params) {
  return useQuery({
    queryKey: ["jobs", params],
    queryFn: () => apiGet<Page<Job>>(`/api/v1/jobs${query(params)}`),
    placeholderData: keepPreviousData,
    refetchInterval: (q) =>
      q.state.data?.items.some((j) => j.status === "queued" || j.status === "running") ? 2000 : false,
  });
}

export function useJobSchedules() {
  return useQuery({
    queryKey: ["job-schedules"],
    queryFn: () => apiGet<JobSchedule[]>("/api/v1/job-schedules"),
  });
}

export function useUpdateSchedule() {
  const invalidate = useInvalidateJobs();
  return useMutation({
    mutationFn: ({ name, ...body }: { name: string; enabled?: boolean; interval_seconds?: number }) =>
      apiPatch<JobSchedule>(`/api/v1/job-schedules/${name}`, body),
    onSuccess: invalidate,
  });
}

export function useRunSchedule() {
  const invalidate = useInvalidateJobs();
  return useMutation({
    mutationFn: (name: string) => apiPost<Job>(`/api/v1/job-schedules/${name}/run`, {}),
    onSuccess: invalidate,
  });
}
