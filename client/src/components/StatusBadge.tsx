// Small pills: receipt status, extraction confidence, inbound-email status, Premium.
import { PiCrown } from "react-icons/pi";
import type { Confidence, InboundLogEntry, ProcessingStatus } from "../api";

const PILL = "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold";

const STATUS: Record<ProcessingStatus, { label: string; cls: string }> = {
  NEEDS_REVIEW: { label: "Needs review", cls: "bg-amber-100 text-amber-950" },
  SAVED: { label: "Saved", cls: "bg-emerald-100 text-emerald-950" },
  FAILED: { label: "Extraction failed", cls: "bg-red-100 text-red-900" },
  ARCHIVED: { label: "Archived", cls: "bg-slate-200 text-slate-800" },
};

export function StatusBadge({ status }: { status: ProcessingStatus }) {
  const s = STATUS[status] ?? { label: status, cls: "bg-slate-100 text-slate-800" };
  return <span className={`${PILL} ${s.cls}`}>{s.label}</span>;
}

const CONFIDENCE: Record<Confidence, { label: string; cls: string }> = {
  HIGH: { label: "High confidence", cls: "bg-emerald-100 text-emerald-950" },
  MEDIUM: { label: "Medium confidence", cls: "bg-amber-100 text-amber-950" },
  LOW: { label: "Low confidence", cls: "bg-red-100 text-red-900" },
  UNKNOWN: { label: "Confidence unknown", cls: "bg-slate-100 text-slate-800" },
};

export function ConfidenceBadge({ value }: { value: Confidence }) {
  const c = CONFIDENCE[value] ?? CONFIDENCE.UNKNOWN;
  return <span className={`${PILL} ${c.cls}`}>{c.label}</span>;
}

const INBOUND: Record<InboundLogEntry["status"], { label: string; cls: string }> = {
  PROCESSED: { label: "Processed", cls: "bg-emerald-100 text-emerald-950" },
  REJECTED: { label: "Rejected", cls: "bg-red-100 text-red-900" },
  DUPLICATE: { label: "Duplicate", cls: "bg-slate-200 text-slate-800" },
  FAILED: { label: "Failed", cls: "bg-red-100 text-red-900" },
};

export function InboundBadge({ status }: { status: InboundLogEntry["status"] }) {
  const s = INBOUND[status] ?? { label: status, cls: "bg-slate-100 text-slate-800" };
  return <span className={`${PILL} ${s.cls}`}>{s.label}</span>;
}

export function PremiumBadge() {
  return (
    <span className={`${PILL} bg-accent text-slate-950`}>
      <PiCrown aria-hidden="true" /> Premium
    </span>
  );
}

export function AiBadge() {
  return <span className={`${PILL} bg-violet-100 text-violet-950`}>AI suggested</span>;
}
