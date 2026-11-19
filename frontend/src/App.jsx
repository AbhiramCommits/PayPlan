import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import LoginPage from "./features/auth/LoginPage";
import RequireAuth from "./features/auth/RequireAuth";
import DashboardPage from "./features/plans/DashboardPage";
import PlanDetailPage from "./features/plans/PlanDetailPage";
import HistoryPage from "./features/payments/HistoryPage";
import OpsPage, { OpsRoute } from "./features/ops/OpsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/plans/:id" element={<PlanDetailPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/ops" element={<OpsRoute />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export { OpsPage };
