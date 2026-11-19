// Three main pages (landing + capture, receipt detail, dashboard). Sign-in and
// registration are modals, so there are no separate login pages.
import { Navigate, Route, Routes } from "react-router-dom";
import { AuthModal } from "./components/AuthModal";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { Dashboard } from "./pages/Dashboard";
import { Landing } from "./pages/Landing";
import { LandingClassic } from "./pages/LandingClassic";
import { Pricing } from "./pages/Pricing";
import { ResetPassword } from "./pages/ResetPassword";
import { ReceiptDetail } from "./pages/ReceiptDetail";

export function App() {
  return (
    <>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Landing />} />
          <Route
            path="/receipts/:id"
            element={
              <RequireAuth>
                <ReceiptDetail />
              </RequireAuth>
            }
          />
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <Dashboard />
              </RequireAuth>
            }
          />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/classic" element={<LandingClassic />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      <AuthModal />
    </>
  );
}
