// Route guard for private pages (dashboard, receipt detail). While the session is
// being checked we show a spinner; if nobody is signed in we send the visitor home
// and open the sign-in modal, then bring them back to where they were going.
import { useEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { PageSpinner } from "./Spinner";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, openAuthModal } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const target = location.pathname + location.search;

  useEffect(() => {
    if (!loading && !user) {
      openAuthModal("login", {
        reason: "Please sign in to see your receipts and account.",
        onSuccess: () => navigate(target, { replace: true }),
      });
      navigate("/", { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, user]);

  if (loading) return <PageSpinner label="Checking your session…" />;
  if (!user) return null;
  return <>{children}</>;
}
