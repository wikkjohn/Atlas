import { Route, Routes } from "react-router-dom";

import { NotFoundPage } from "@/app/NotFoundPage";
import { AppShell } from "@/components/AppShell";
import { OverviewPage } from "@/features/dashboard/OverviewPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
