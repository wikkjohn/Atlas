import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiPatch, apiPost, query } from "@/services/api";
import type {
  AuditEvent,
  Country,
  CountryCalendar,
  CountrySample,
  Currency,
  Employee,
  Organization,
  Page,
  Role,
  UserAccount,
  UserCreate,
  ValueCheck,
} from "@/types/enterprise";

type Params = Record<string, string | number | boolean | null | undefined>;

// --- Countries ---------------------------------------------------------------------------

export function useCountries(params: Params = {}) {
  return useQuery({
    queryKey: ["countries", params],
    queryFn: () => apiGet<Page<Country>>(`/api/v1/countries${query({ limit: 200, ...params })}`),
  });
}

export function useCreateCountry() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => apiPost<Country>("/api/v1/countries", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["countries"] }),
  });
}

export function useUpdateCountry() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) =>
      apiPatch<Country>(`/api/v1/countries/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["countries"] }),
  });
}

export const useCurrencies = () =>
  useQuery({
    queryKey: ["currencies"],
    queryFn: () => apiGet<Currency[]>("/api/v1/currencies"),
    staleTime: Infinity,
  });

export const useCountryCalendar = (id: string, year: number) =>
  useQuery({
    queryKey: ["countries", "calendar", id, year],
    queryFn: () => apiGet<CountryCalendar>(`/api/v1/countries/${id}/calendar${query({ year })}`),
  });

export const useCountrySamples = (id: string, seed: number) =>
  useQuery({
    queryKey: ["countries", "samples", id, seed],
    queryFn: () => apiGet<CountrySample[]>(`/api/v1/countries/${id}/samples${query({ count: 3, seed })}`),
  });

export const useCheckCountryValue = (id: string) =>
  useMutation({
    mutationFn: (body: { kind: string; value: string }) => apiPost<ValueCheck>(`/api/v1/countries/${id}/check`, body),
  });

// --- Organizations -----------------------------------------------------------------------

export function useOrganizations(params: Params, enabled = true) {
  return useQuery({
    queryKey: ["organizations", "list", params],
    queryFn: () =>
      apiGet<Page<Organization>>(`/api/v1/organizations${query({ limit: 200, ...params })}`),
    enabled,
  });
}

export function useOrganization(id: string | null) {
  return useQuery({
    queryKey: ["organizations", "detail", id],
    queryFn: () => apiGet<Organization>(`/api/v1/organizations/${id}`),
    enabled: Boolean(id),
  });
}

export function useAncestors(id: string | null) {
  return useQuery({
    queryKey: ["organizations", "ancestors", id],
    queryFn: () => apiGet<Organization[]>(`/api/v1/organizations/${id}/ancestors`),
    enabled: Boolean(id),
  });
}

export function useCreateOrganization() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => apiPost<Organization>("/api/v1/organizations", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["organizations"] }),
  });
}

export function useUpdateOrganization() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) =>
      apiPatch<Organization>(`/api/v1/organizations/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["organizations"] }),
  });
}

// --- Employees ---------------------------------------------------------------------------

export function useEmployees(params: Params, enabled = true) {
  return useQuery({
    queryKey: ["employees", "list", params],
    queryFn: () => apiGet<Page<Employee>>(`/api/v1/employees${query(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useEmployee(id: string | null) {
  return useQuery({
    queryKey: ["employees", "detail", id],
    queryFn: () => apiGet<Employee>(`/api/v1/employees/${id}`),
    enabled: Boolean(id),
  });
}

export function useReportingChain(id: string | null) {
  return useQuery({
    queryKey: ["employees", "chain", id],
    queryFn: () => apiGet<Employee[]>(`/api/v1/employees/${id}/reporting-chain`),
    enabled: Boolean(id),
  });
}

export function useDirectReports(id: string | null) {
  return useQuery({
    queryKey: ["employees", "reports", id],
    queryFn: () => apiGet<Employee[]>(`/api/v1/employees/${id}/direct-reports`),
    enabled: Boolean(id),
  });
}

export function useCreateEmployee() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => apiPost<Employee>("/api/v1/employees", body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["employees"] });
      void client.invalidateQueries({ queryKey: ["organizations"] });
    },
  });
}

export function useUpdateEmployee() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) =>
      apiPatch<Employee>(`/api/v1/employees/${id}`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["employees"] });
      void client.invalidateQueries({ queryKey: ["organizations"] });
    },
  });
}

// --- Audit & roles -----------------------------------------------------------------------

export function useAuditEvents(params: Params) {
  return useQuery({
    queryKey: ["audit-events", params],
    queryFn: () => apiGet<Page<AuditEvent>>(`/api/v1/audit-events${query(params)}`),
    placeholderData: keepPreviousData,
  });
}

export function useRoles() {
  return useQuery({
    queryKey: ["roles"],
    queryFn: () => apiGet<Role[]>("/api/v1/roles"),
    staleTime: Infinity,
  });
}

// --- Users (System Settings) ----------------------------------------------------------------

export function useUsers(params: Params, enabled = true) {
  return useQuery({
    queryKey: ["users", params],
    queryFn: () => apiGet<Page<UserAccount>>(`/api/v1/users${query(params)}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: UserCreate) => apiPost<UserAccount>("/api/v1/users", body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUpdateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: string; is_active?: boolean }) =>
      apiPatch<UserAccount>(`/api/v1/users/${id}`, body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["users"] }),
  });
}
