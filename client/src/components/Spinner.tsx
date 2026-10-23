import { PiSpinnerGap } from "react-icons/pi";

/** Inline spinner; with a label it also shows (and announces) the text. */
export function Spinner({ className = "", label }: { className?: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2" role={label ? "status" : undefined}>
      <PiSpinnerGap className={`h-5 w-5 animate-spin ${className}`} aria-hidden="true" />
      {label ? <span>{label}</span> : <span className="sr-only">Loading</span>}
    </span>
  );
}

export function PageSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex justify-center py-20 text-slate-700">
      <Spinner className="text-brand" label={label} />
    </div>
  );
}
