import { lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { NotFoundPage } from "@/app/NotFoundPage";
import { RequireAuth } from "@/app/RequireAuth";
import { AppShell } from "@/components/AppShell";
import { LoginPage } from "@/features/auth/LoginPage";
import { OverviewPage } from "@/features/dashboard/OverviewPage";

// Feature screens load on first visit (keeps the initial bundle small).
const AccountsPage = lazy(() => import("@/features/accounts/AccountsPage").then((m) => ({ default: m.AccountsPage })));
const AiLabPage = lazy(() => import("@/features/ai-lab/AiLabPage").then((m) => ({ default: m.AiLabPage })));
const AuditPage = lazy(() => import("@/features/audit/AuditPage").then((m) => ({ default: m.AuditPage })));
const BenchmarkingPage = lazy(() => import("@/features/benchmarking/BenchmarkingPage").then((m) => ({ default: m.BenchmarkingPage })));
const CountriesPage = lazy(() => import("@/features/countries/CountriesPage").then((m) => ({ default: m.CountriesPage })));
const CustomersPage = lazy(() => import("@/features/customers/CustomersPage").then((m) => ({ default: m.CustomersPage })));
const EmployeesPage = lazy(() => import("@/features/employees/EmployeesPage").then((m) => ({ default: m.EmployeesPage })));
const ExperimentsPage = lazy(() => import("@/features/experiments/ExperimentsPage").then((m) => ({ default: m.ExperimentsPage })));
const LoansPage = lazy(() => import("@/features/lending/LoansPage").then((m) => ({ default: m.LoansPage })));
const OrganizationPage = lazy(() => import("@/features/organizations/OrganizationPage").then((m) => ({ default: m.OrganizationPage })));
const PaymentsPage = lazy(() => import("@/features/payments/PaymentsPage").then((m) => ({ default: m.PaymentsPage })));
const TradePage = lazy(() => import("@/features/trade/TradePage").then((m) => ({ default: m.TradePage })));
const PaymentOpsPage = lazy(() => import("@/features/payment-ops/PaymentOpsPage").then((m) => ({ default: m.PaymentOpsPage })));
const CompliancePage = lazy(() => import("@/features/compliance/CompliancePage").then((m) => ({ default: m.CompliancePage })));
const WealthPage = lazy(() => import("@/features/wealth/WealthPage").then((m) => ({ default: m.WealthPage })));
const TreasuryPage = lazy(() => import("@/features/treasury/TreasuryPage").then((m) => ({ default: m.TreasuryPage })));
const CommercialPage = lazy(() => import("@/features/commercial/CommercialPage").then((m) => ({ default: m.CommercialPage })));
const MortgagesPage = lazy(() => import("@/features/mortgages/MortgagesPage").then((m) => ({ default: m.MortgagesPage })));
const CardsPage = lazy(() => import("@/features/cards/CardsPage").then((m) => ({ default: m.CardsPage })));
const RetailPage = lazy(() => import("@/features/retail/RetailPage").then((m) => ({ default: m.RetailPage })));
const FxPage = lazy(() => import("@/features/fx/FxPage").then((m) => ({ default: m.FxPage })));
const SettingsPage = lazy(() => import("@/features/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const SimulationCenterPage = lazy(() => import("@/features/simulations/SimulationCenterPage").then((m) => ({ default: m.SimulationCenterPage })));
const WorkflowExplorerPage = lazy(() => import("@/features/workflows/WorkflowExplorerPage").then((m) => ({ default: m.WorkflowExplorerPage })));

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
        <Route path="payments" element={<PaymentsPage />} />
        <Route path="fx" element={<FxPage />} />
        <Route path="retail" element={<RetailPage />} />
        <Route path="cards" element={<CardsPage />} />
        <Route path="mortgages" element={<MortgagesPage />} />
        <Route path="commercial" element={<CommercialPage />} />
        <Route path="trade" element={<TradePage />} />
        <Route path="treasury" element={<TreasuryPage />} />
        <Route path="payment-ops" element={<PaymentOpsPage />} />
        <Route path="wealth" element={<WealthPage />} />
        <Route path="compliance" element={<CompliancePage />} />
        <Route path="lending" element={<LoansPage />} />
        <Route path="workflows" element={<WorkflowExplorerPage />} />
        <Route path="simulations" element={<SimulationCenterPage />} />
        <Route path="ai-lab" element={<AiLabPage />} />
        <Route path="experiments" element={<ExperimentsPage />} />
        <Route path="benchmarking" element={<BenchmarkingPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
