// Usage, plan comparison and the upgrade flow (real Stripe, or a clearly labelled demo).
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiErrorInfo,
  demoDowngrade,
  demoUpgrade,
  getBillingStatus,
  openBillingPortal,
  startCheckout,
  type PlanInfo,
} from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { useUsage } from "../hooks/useUsage";
import { formatDate } from "../lib/format";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { Card } from "./Card";
import { ConfirmDialog } from "./ConfirmDialog";
import { FeatureMatrix, PlanCards } from "./PlanCards";
import { PageSpinner, Spinner } from "./Spinner";
import { UsageMeter } from "./UsageMeter";

export function PlanTab({ goTo: _goTo }: { goTo: (t: "plan") => void }) {
  const { user, refresh } = useAuth();
  const { data: config } = useConfig();
  const { data: usage } = useUsage();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const { data: billing } = useQuery({ queryKey: ["billing"], queryFn: getBillingStatus, retry: false });

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [confirmDowngrade, setConfirmDowngrade] = useState(false);
  const returning = useRef(params.get("billing"));

  const mode = config?.services.billing_mode;

  async function syncAll() {
    await refresh();
    await queryClient.invalidateQueries({ queryKey: ["usage"] });
    await queryClient.invalidateQueries({ queryKey: ["billing"] });
    await queryClient.invalidateQueries({ queryKey: ["receipts"] });
  }

  // Back from Stripe Checkout: the plan changes via webhook, so poll for a few seconds.
  useEffect(() => {
    const outcome = returning.current;
    if (!outcome) return;
    const clear = () => {
      const p = new URLSearchParams(params);
      p.delete("billing");
      p.set("tab", "plan");
      setParams(p, { replace: true });
    };
    if (outcome === "cancel") {
      setError(null);
      setSuccess(null);
      clear();
      return;
    }
    if (outcome !== "success") return;
    let cancelled = false;
    setPolling(true);
    (async () => {
      for (let i = 0; i < 8 && !cancelled; i++) {
        try {
          const s = await getBillingStatus();
          if (s.plan === "PREMIUM") {
            await syncAll();
            if (!cancelled) {
              setSuccess("Thanks. Your Premium subscription is active.");
              setPolling(false);
              clear();
            }
            return;
          }
        } catch {
          /* keep trying */
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
      if (!cancelled) {
        setPolling(false);
        setError("We haven't received confirmation from the payment provider yet. This can take a minute: refresh this page shortly to check your plan.");
        clear();
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run(fn: () => Promise<void>, ok?: string) {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      await fn();
      if (ok) setSuccess(ok);
    } catch (err) {
      const info = apiErrorInfo(err);
      setError(info.code === "billing_demo_mode" ? "Billing is in demo mode on this server, so real checkout isn't available." : info.message);
    } finally {
      setBusy(false);
    }
  }

  const upgrade = () =>
    run(async () => {
      if (mode === "stripe") {
        const { url } = await startCheckout();
        window.location.href = url;
        return;
      }
      await demoUpgrade();
      await syncAll();
    }, mode === "stripe" ? undefined : "Demo upgrade applied: your account is now on Premium. No payment was taken.");

  const portal = () =>
    run(async () => {
      const { url } = await openBillingPortal();
      window.location.href = url;
    });

  const downgradeDemo = () =>
    run(async () => {
      await demoDowngrade();
      await syncAll();
      setConfirmDowngrade(false);
    }, "Demo downgrade applied: your account is back on the Free plan.");

  if (!config || !user) return <PageSpinner />;

  function action(plan: PlanInfo) {
    const isPremium = plan.id === "PREMIUM";
    if (isPremium && user!.plan === "FREE") {
      return (
        <Button className="w-full" variant="accent" disabled={busy || polling} onClick={() => void upgrade()}>
          {busy ? <Spinner label="Working…" /> : mode === "stripe" ? "Upgrade to Premium" : "Try Premium (demo, no payment)"}
        </Button>
      );
    }
    if (isPremium && user!.plan === "PREMIUM") {
      return mode === "stripe" ? (
        billing?.can_manage ? (
          <Button className="w-full" variant="secondary" disabled={busy} onClick={() => void portal()}>
            Manage subscription
          </Button>
        ) : (
          <p className="text-sm text-slate-700">You're on Premium.</p>
        )
      ) : (
        <Button className="w-full" variant="secondary" disabled={busy} onClick={() => setConfirmDowngrade(true)}>
          Switch back to Free (demo)
        </Button>
      );
    }
    return null;
  }

  return (
    <div className="space-y-5">
      {polling ? (
        <Alert kind="info">
          <Spinner label="Confirming your subscription with the payment provider…" />
        </Alert>
      ) : null}
      {success ? <Alert kind="success">{success}</Alert> : null}
      {error ? <Alert kind="error">{error}</Alert> : null}

      <Card className="space-y-3 p-4">
        <h2 className="text-lg font-bold text-ink">Receipt usage</h2>
        {usage ? <UsageMeter usage={usage} /> : <Spinner className="text-brand" label="Loading usage…" />}
        <p className="text-xs text-slate-600">
          Only receipts you have saved count. Failed uploads and duplicates don't use your allowance. The
          limit is enforced by the server.
        </p>
      </Card>

      {mode === "demo" ? (
        <Alert kind="warning" title="Demo billing: no payment is taken">
          Upgrades on this site are simulated to show how Premium behaves. No card is needed and no money
          changes hands.
        </Alert>
      ) : mode === "stripe" ? (
        <Alert kind="info">
          Payments are handled by Stripe in CAD. TradeTrack never sees or stores your card details.
        </Alert>
      ) : null}

      <section aria-labelledby="plans-h" className="space-y-3">
        <h2 id="plans-h" className="text-lg font-bold text-ink">Plans</h2>
        <PlanCards config={config} currentPlan={user.plan} renderAction={action} />
        <FeatureMatrix config={config} />
      </section>

      {billing && user.plan === "PREMIUM" ? (
        <Card className="p-4 text-sm">
          <h2 className="font-bold text-ink">Subscription</h2>
          <dl className="mt-2 space-y-1 text-slate-800">
            <div className="flex justify-between gap-3"><dt>Status</dt><dd className="font-medium">{billing.subscription_status ?? "Not available"}</dd></div>
            {billing.current_period_end ? (
              <div className="flex justify-between gap-3">
                <dt>{billing.cancel_at_period_end ? "Ends on" : "Renews on"}</dt>
                <dd className="font-medium">{formatDate(billing.current_period_end)}</dd>
              </div>
            ) : null}
          </dl>
          {billing.cancel_at_period_end ? <p className="mt-2 text-amber-900">Your subscription is set to end at the close of this period.</p> : null}
        </Card>
      ) : null}

      {confirmDowngrade ? (
        <ConfirmDialog
          title="Switch back to Free? (demo)"
          confirmLabel="Switch to Free"
          busy={busy}
          onCancel={() => setConfirmDowngrade(false)}
          onConfirm={() => void downgradeDemo()}
        >
          This changes your plan in the demo only. Your receipts stay, but Premium features such as
          exports and email forwarding will lock again.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
