// Pricing: Free vs Premium side by side, the full comparison, and straight answers.
import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { PlanCards, FeatureMatrix } from "../components/PlanCards";
import { UpgradeButton } from "../components/UpgradeButton";
import { useConfig } from "../hooks/useConfig";

export function Pricing() {
  const { user, openAuthModal } = useAuth();
  const { data: config, isError, failureCount } = useConfig();

  return (
    <div className="space-y-8">
      <header className="max-w-2xl">
        <h1 className="text-3xl font-extrabold tracking-tight text-ink">Free to start. Premium when you need more.</h1>
        <p className="mt-2 text-slate-700">
          Save your first receipts on the Free plan. Upgrade when you want unlimited receipts, summaries by month,
          quarter or year, and exports for your accountant.
        </p>
      </header>

      {config ? (
        <>
          <PlanCards
            config={config}
            currentPlan={user?.plan}
            renderAction={(plan) =>
              plan.id === "PREMIUM" ? (
                <UpgradeButton />
              ) : user ? null : (
                <Button className="w-full" variant="secondary" onClick={() => openAuthModal("register")}>
                  Start free
                </Button>
              )
            }
          />
          <section aria-labelledby="compare-title" className="space-y-3">
            <h2 id="compare-title" className="text-xl font-bold text-ink">Compare plans</h2>
            <FeatureMatrix config={config} />
          </section>
        </>
      ) : isError ? (
        <Alert kind="warning" title="Couldn't load the plans">Please refresh the page in a moment.</Alert>
      ) : (
        <Alert kind="info" title={failureCount > 0 ? "The server is waking up" : "Loading plans…"}>
          TradeTrack runs on a free hosting plan that sleeps when idle, so the first visit can take up to a minute.
          This page updates by itself.
        </Alert>
      )}

      <section aria-labelledby="faq-title" className="space-y-3">
        <h2 id="faq-title" className="text-xl font-bold text-ink">Good to know</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <Card className="p-4">
            <h3 className="font-semibold text-ink">What counts toward the Free limit?</h3>
            <p className="mt-1 text-sm text-slate-700">
              Only receipts you review and save. Uploads that fail, duplicates and receipts still waiting for review
              don't count. The allowance resets at the start of each calendar month.
            </p>
          </Card>
          <Card className="p-4">
            <h3 className="font-semibold text-ink">Do I have to create an account to try it?</h3>
            <p className="mt-1 text-sm text-slate-700">
              You can <Link to="/#sample" className="font-semibold text-brand underline">watch a sample receipt being read</Link>{" "}
              without signing up. Reading your own receipts needs a free account so they stay private to you.
            </p>
          </Card>
          <Card className="p-4">
            <h3 className="font-semibold text-ink">Is the category or tax information advice?</h3>
            <p className="mt-1 text-sm text-slate-700">
              No. Categories and tax details are suggestions you can change. Whether an expense is deductible or tax is
              recoverable is for you and your accountant to decide.
            </p>
          </Card>
          <Card className="p-4">
            <h3 className="font-semibold text-ink">Do I need a credit card for the Free plan?</h3>
            <p className="mt-1 text-sm text-slate-700">No. Free needs only an email address and a password.</p>
          </Card>
        </div>
      </section>
    </div>
  );
}
