// "What Premium adds" card for Free accounts. The buttons look like the real Premium actions but are
// locked: they are never wired to the API, they only open a short explanation with the upgrade link.
// Wording follows the invariants: no deductibility claims; email forwarding stays "coming soon"
// until the server says inbound email is configured.
import { useState } from "react";
import { Link } from "react-router-dom";
import { PiCrownSimple, PiDownloadSimple, PiFileText, PiFileZip, PiLockSimple } from "react-icons/pi";
import type { IconType } from "react-icons";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { buttonClasses } from "./Button";
import { Card } from "./Card";
import { Modal } from "./Modal";

const LOCKED: { id: string; label: string; icon: IconType; title: string; text: string }[] = [
  {
    id: "csv",
    label: "Export CSV",
    icon: PiDownloadSimple,
    title: "Export your receipts",
    text: "Download your saved receipts as a CSV or JSON file for your bookkeeping, for any month, range or the whole year.",
  },
  {
    id: "summary",
    label: "Summary by province",
    icon: PiFileText,
    title: "Expense summary",
    text: "See your expenses by month, quarter or year, split by category, tax type and province, as a PDF or CSV.",
  },
  {
    id: "package",
    label: "Accountant package",
    icon: PiFileZip,
    title: "Accountant package",
    text: "One ZIP with the summary, a receipts CSV and the original files, ready to send to your accountant. Your accountant decides what applies to you.",
  },
];

export function PremiumStrip() {
  const { user } = useAuth();
  const { data: config } = useConfig();
  const [open, setOpen] = useState<(typeof LOCKED)[number] | null>(null);
  if (!user || user.plan === "PREMIUM") return null;
  const forwardingLive = config?.services.inbound_email_configured === true;

  return (
    <Card className="border-amber-300 bg-accent-soft p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-semibold text-ink">
            <PiCrownSimple className="h-5 w-5 text-amber-800" aria-hidden="true" /> What Premium adds
          </p>
          <p className="mt-1 text-sm text-slate-800">
            Unlimited saved receipts, plus the exports below
            {forwardingLive ? " and email forwarding" : " (email forwarding is coming soon)"}. $5.99/month.
          </p>
        </div>
        <Link to="/dashboard?tab=plan" className={buttonClasses("accent", "sm")}>
          See Premium
        </Link>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {LOCKED.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setOpen(f)}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white/70 px-3 text-sm font-semibold text-slate-600 hover:bg-white"
          >
            <f.icon aria-hidden="true" /> {f.label}
            <PiLockSimple className="text-amber-800" aria-hidden="true" />
            <span className="sr-only">(Premium)</span>
          </button>
        ))}
      </div>
      {open ? (
        <Modal
          title={`${open.title} is a Premium feature`}
          onClose={() => setOpen(null)}
          size="sm"
          footer={
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" className={buttonClasses("secondary", "md")} onClick={() => setOpen(null)}>
                Not now
              </button>
              <Link to="/dashboard?tab=plan" className={buttonClasses("accent", "md")} onClick={() => setOpen(null)}>
                See Premium
              </Link>
            </div>
          }
        >
          <p className="text-sm text-slate-800">{open.text}</p>
          <p className="mt-2 text-sm text-slate-700">Free accounts can still download each receipt's PDF summary from its page.</p>
        </Modal>
      ) : null}
    </Card>
  );
}
