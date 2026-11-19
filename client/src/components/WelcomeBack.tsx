// Home for a signed-in user: a greeting, their allowance, a quick way to add a receipt, and the latest
// receipts. The full history, exports and settings live on the dashboard.
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listReceipts } from "../api";
import { useAuth } from "../auth";
import { useUsage } from "../hooks/useUsage";
import { money, formatDate } from "../lib/format";
import { buttonClasses } from "./Button";
import { Card } from "./Card";
import { StatusBadge } from "./StatusBadge";
import { UploadPanel } from "./UploadPanel";
import { UsageMeter } from "./UsageMeter";

export function WelcomeBack() {
  const { user } = useAuth();
  const { data: usage } = useUsage();
  const { data: recent } = useQuery({ queryKey: ["receipts", "recent"], queryFn: () => listReceipts({ limit: 4 }) });
  if (!user) return null;
  const needsReview = recent?.items.filter((r) => r.processing_status === "NEEDS_REVIEW").length ?? 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-extrabold tracking-tight text-ink">Welcome back, {user.first_name}</h1>
        <p className="mt-1 text-slate-700">Add a receipt below, or pick up where you left off.</p>
      </header>

      <UploadPanel />

      {usage ? (
        <Card className="space-y-2 p-4">
          <UsageMeter usage={usage} compact />
          {user.plan !== "PREMIUM" ? (
            <p className="text-sm text-slate-700">
              Need more than {usage.limit} a month, or summaries and exports for your accountant?{" "}
              <Link to="/pricing" className="font-semibold text-brand underline">
                See Premium
              </Link>
            </p>
          ) : null}
        </Card>
      ) : null}

      <section aria-labelledby="recent-title" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="recent-title" className="text-xl font-bold text-ink">
            Latest receipts
          </h2>
          <Link to="/dashboard" className={buttonClasses("secondary", "sm")}>
            Go to my dashboard
          </Link>
        </div>
        {needsReview > 0 ? (
          <p className="text-sm font-medium text-amber-900">
            {needsReview} receipt{needsReview === 1 ? "" : "s"} waiting for your review.
          </p>
        ) : null}
        {recent && recent.items.length === 0 ? (
          <Card className="p-4 text-sm text-slate-700">No receipts yet. Add your first one above.</Card>
        ) : (
          <ul className="space-y-2">
            {recent?.items.map((r) => (
              <li key={r.id}>
                <Card className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <Link to={`/receipts/${r.id}`} className="min-w-0 break-words font-semibold text-brand hover:underline">
                    {r.merchant ?? "Receipt"}
                  </Link>
                  <span className="flex flex-wrap items-center gap-3 text-sm text-slate-700">
                    <span>{r.receipt_date ? formatDate(r.receipt_date) : "No date"}</span>
                    <span className="font-medium text-ink">{r.total ? money(r.total, r.currency) : "Not available"}</span>
                    <StatusBadge status={r.processing_status} />
                  </span>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
