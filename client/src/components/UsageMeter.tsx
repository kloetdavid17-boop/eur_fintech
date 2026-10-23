import type { Usage } from "../api";
import { formatDate } from "../lib/format";

/** Monthly allowance meter. The numbers come straight from the server (/receipts/usage). */
export function UsageMeter({ usage, compact = false }: { usage: Usage; compact?: boolean }) {
  const unlimited = usage.limit === null;
  const pct = unlimited ? 0 : Math.min(100, Math.round((usage.saved_this_period / usage.limit!) * 100));
  const full = !unlimited && usage.saved_this_period >= usage.limit!;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className={`font-semibold text-ink ${compact ? "text-sm" : "text-base"}`}>
          {unlimited
            ? `${usage.saved_this_period} receipt${usage.saved_this_period === 1 ? "" : "s"} saved in ${usage.period_label}`
            : `${usage.saved_this_period} of ${usage.limit} receipts saved in ${usage.period_label}`}
        </p>
        <p className="text-xs text-slate-600">
          {unlimited ? "Unlimited on Premium" : `Resets ${formatDate(usage.resets_on)}`}
        </p>
      </div>
      {unlimited ? null : (
        <div
          role="progressbar"
          aria-label="Monthly saved receipts"
          aria-valuemin={0}
          aria-valuemax={usage.limit ?? 0}
          aria-valuenow={usage.saved_this_period}
          className="mt-2 h-2.5 overflow-hidden rounded-full bg-slate-200"
        >
          <div
            className={`h-full rounded-full ${full ? "bg-red-600" : pct >= 80 ? "bg-amber-500" : "bg-brand"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      {full ? (
        <p className="mt-2 text-sm font-medium text-red-800">
          You've used this month's free allowance. You can still upload and review receipts, but you'll
          need Premium (or next month) to save more.
        </p>
      ) : null}
    </div>
  );
}
