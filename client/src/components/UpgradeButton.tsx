// One-click upgrade from anywhere (the plan cards on the main page). Signed-out visitors get the
// sign-up form first and then go straight on to upgrade. In Stripe mode this opens Stripe Checkout;
// in demo mode it applies the clearly labelled demo upgrade. Which one runs is decided by the server
// (config.services.billing_mode), never by the browser.
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PiCrownSimple } from "react-icons/pi";
import { apiErrorInfo, demoUpgrade, startCheckout, type User } from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { Alert } from "./Alert";
import { Button, buttonClasses } from "./Button";
import { Spinner } from "./Spinner";

export function UpgradeButton({ className = "" }: { className?: string }) {
  const { user, openAuthModal, refresh, setNotice } = useAuth();
  const { data: config } = useConfig();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mode = config?.services.billing_mode;

  if (!config) return null;

  if (user?.plan === "PREMIUM") {
    return (
      <Link to="/dashboard" className={buttonClasses("secondary", "md", `w-full ${className}`)}>
        You're on Premium. Open your dashboard
      </Link>
    );
  }

  async function upgrade(who: User) {
    setBusy(true);
    setError(null);
    try {
      if (mode === "stripe") {
        const { url } = await startCheckout();
        window.location.href = url; // Stripe Checkout; it returns to /dashboard?billing=success
        return;
      }
      const { confirmation_email: sent } = await demoUpgrade();
      await refresh();
      await queryClient.invalidateQueries({ queryKey: ["usage"] });
      await queryClient.invalidateQueries({ queryKey: ["billing"] });
      setNotice({
        kind: "success",
        text:
          "Demo upgrade applied: your account is now on Premium. No payment was taken." +
          (sent === "sent" ? ` A confirmation email was sent to ${who.email}.` : sent === "failed" ? " We couldn't send the confirmation email." : ""),
      });
    } catch (err) {
      const info = apiErrorInfo(err);
      setError(info.code === "already_premium" ? "You are already on Premium." : info.message);
    } finally {
      setBusy(false);
    }
  }

  function click() {
    if (user) void upgrade(user);
    else
      openAuthModal("register", {
        reason: "Create your free account first, then you'll go straight on to Premium.",
        onSuccess: (u) => void upgrade(u),
      });
  }

  return (
    <div className={className}>
      <Button className="w-full" variant="accent" disabled={busy} onClick={click}>
        {busy ? (
          <Spinner label="Working…" />
        ) : (
          <>
            <PiCrownSimple aria-hidden="true" />
            {mode === "stripe" ? "Upgrade to Premium" : "Try Premium (demo, no payment)"}
          </>
        )}
      </Button>
      {!user ? <p className="mt-1.5 text-center text-xs text-slate-600">You'll create a free account first.</p> : null}
      {error ? <Alert kind="error" className="mt-2">{error}</Alert> : null}
    </div>
  );
}
