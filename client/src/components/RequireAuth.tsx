// Route guard for private pages (dashboard, receipt detail). While the session is being checked we show
// a spinner. A visitor who is not signed in sees a short "sign in to continue" page right here, with
// sign-in, create-account and back-to-home options. Signing in keeps them on the page they asked for.
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { PiArrowLeft, PiLockSimple } from "react-icons/pi";
import { useAuth } from "../auth";
import { Button, buttonClasses } from "./Button";
import { Card } from "./Card";
import { PageSpinner } from "./Spinner";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, openAuthModal } = useAuth();
  const { pathname } = useLocation();

  if (loading) return <PageSpinner label="Checking your session…" />;
  if (user) return <>{children}</>;

  const what = pathname.startsWith("/receipts/") ? "this receipt" : "your dashboard";
  return (
    <div className="mx-auto max-w-md py-10">
      <Card className="space-y-4 p-6 text-center">
        <PiLockSimple className="mx-auto h-9 w-9 text-brand" aria-hidden="true" />
        <div>
          <h1 className="text-xl font-extrabold text-ink">Sign in to see {what}</h1>
          <p className="mt-1 text-sm text-slate-700">
            Your receipts and account are private to you, so you need to be signed in. Signing in or creating a free
            account takes you straight back here.
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <Button size="lg" onClick={() => openAuthModal("login")}>
            Sign in
          </Button>
          <Button size="lg" variant="secondary" onClick={() => openAuthModal("register")}>
            Create free account
          </Button>
        </div>
        <Link to="/" className={`${buttonClasses("ghost", "sm")} mx-auto`}>
          <PiArrowLeft aria-hidden="true" /> Back to home
        </Link>
      </Card>
    </div>
  );
}
