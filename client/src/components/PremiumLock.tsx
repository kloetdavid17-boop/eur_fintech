// Shown in place of a Premium-only feature for Free accounts. Explains what is locked
// and offers the upgrade — the locked controls are never wired to the API.
import type { ReactNode } from "react";
import { PiLockSimple } from "react-icons/pi";
import { PremiumBadge } from "./StatusBadge";
import { Button } from "./Button";

export function PremiumLock({
  title,
  children,
  onUpgrade,
}: {
  title: string;
  children?: ReactNode;
  onUpgrade: () => void;
}) {
  return (
    <div className="rounded-xl border border-amber-300 bg-accent-soft p-4">
      <div className="flex items-start gap-3">
        <PiLockSimple className="mt-0.5 h-6 w-6 shrink-0 text-amber-800" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-semibold text-ink">
            {title} <PremiumBadge />
          </p>
          {children ? <div className="mt-1 text-sm text-slate-800">{children}</div> : null}
          <Button variant="accent" size="sm" className="mt-3" onClick={onUpgrade}>
            See Premium
          </Button>
        </div>
      </div>
    </div>
  );
}
