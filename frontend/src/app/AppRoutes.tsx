import { Route, Routes } from "react-router-dom";

import { NotFoundPage } from "@/app/NotFoundPage";
import { RequireAuth } from "@/app/RequireAuth";
import { AppShell } from "@/components/AppShell";
import { AccountsPage } from "@/features/accounts/AccountsPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { CountriesPage } from "@/features/countries/CountriesPage";
import { CustomersPage } from "@/features/customers/CustomersPage";
import { OverviewPage } from "@/features/dashboard/OverviewPage";
import { EmployeesPage } from "@/features/employees/EmployeesPage";
import { OrganizationPage } from "@/features/organizations/OrganizationPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="organization" element={<OrganizationPage />} />
        <Route path="countries" element={<CountriesPage />} />
        <Route path="employees" element={<EmployeesPage />} />
        <Route path="customers" element={<CustomersPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
