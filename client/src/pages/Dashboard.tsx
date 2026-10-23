// Page 3: account and management dashboard. Sections are tabs, kept in the URL (?tab=).
import { useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../auth";
import { Card } from "../components/Card";
import { ExportsTab } from "../components/ExportsTab";
import { ForwardingTab } from "../components/ForwardingTab";
import { PlanTab } from "../components/PlanTab";
import { ProfileTab } from "../components/ProfileTab";
import { ReceiptsTab } from "../components/ReceiptsTab";
import { UsageMeter } from "../components/UsageMeter";
import { PremiumBadge } from "../components/StatusBadge";
import { useUsage } from "../hooks/useUsage";

export const TABS = [
  { id: "receipts", label: "Receipts" },
  { id: "plan", label: "Usage and plan" },
  { id: "forwarding", label: "Email forwarding" },
  { id: "exports", label: "Exports" },
  { id: "account", label: "Profile and privacy" },
] as const;
export type TabId = (typeof TABS)[number]["id"];

export function Dashboard() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const { data: usage } = useUsage();
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  // Returning from Stripe lands on /dashboard?billing=success: show the plan tab.
  const requested = params.get("tab") ?? (params.get("billing") ? "plan" : "receipts");
  const tab: TabId = TABS.some((t) => t.id === requested) ? (requested as TabId) : "receipts";

  function setTab(next: TabId) {
    const p = new URLSearchParams(params);
    p.set("tab", next);
    p.delete("billing");
    setParams(p, { replace: true });
  }

  function onKey(e: React.KeyboardEvent, index: number) {
    const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const next = TABS[(index + dir + TABS.length) % TABS.length];
    setTab(next.id);
    tabRefs.current[next.id]?.focus();
  }

  if (!user) return null;
  const name = user.business_name || `${user.first_name} ${user.last_name}`;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold text-ink">Dashboard</h1>
          <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
            <span className="break-words">{name}</span>
            {user.plan === "PREMIUM" ? <PremiumBadge /> : <span className="rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-800">Free plan</span>}
          </p>
        </div>
      </header>

      {usage ? (
        <Card className="p-4">
          <UsageMeter usage={usage} compact />
        </Card>
      ) : null}

      <div role="tablist" aria-label="Dashboard sections" className="-mx-4 flex gap-1 overflow-x-auto border-b border-slate-200 px-4">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              tabRefs.current[t.id] = el;
            }}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => onKey(e, i)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-semibold ${
              tab === t.id ? "border-brand text-brand" : "border-transparent text-slate-700 hover:text-slate-950"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "receipts" ? <ReceiptsTab goTo={setTab} /> : null}
        {tab === "plan" ? <PlanTab goTo={setTab} /> : null}
        {tab === "forwarding" ? <ForwardingTab goTo={setTab} /> : null}
        {tab === "exports" ? <ExportsTab goTo={setTab} /> : null}
        {tab === "account" ? <ProfileTab /> : null}
      </div>
    </div>
  );
}
