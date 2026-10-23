// An illustrative walk-through of the workflow on the landing page. Nothing here is
// retrieved from a real transaction or sent to the server — the label says so, and
// the final step explicitly states that nothing is stored.
import { useState } from "react";
import { PiCheckCircle, PiSparkle } from "react-icons/pi";
import { money } from "../lib/format";
import { Button } from "./Button";
import { Card } from "./Card";

// Invented merchant and numbers (illustrative only). 153.08 x 13% HST = 19.90.
const SAMPLE = {
  merchant: "Maple Ridge Building Supply (sample)",
  address: "Hamilton, ON",
  date: "2026-09-18",
  number: "SAMPLE-004217",
  lines: [
    { description: "SPF 2x4x8 stud", qty: 20, unit: "4.28", amount: "85.60" },
    { description: "Drill bit set", qty: 1, unit: "39.99", amount: "39.99" },
    { description: "Deck screws, 5 lb box", qty: 1, unit: "27.49", amount: "27.49" },
  ],
  subtotal: "153.08",
  tax: { label: "HST 13%", amount: "19.90" },
  total: "172.98",
  category: "Building materials and supplies",
};

type Step = "read" | "confirmed" | "saved";

export function SampleReceiptDemo() {
  const [step, setStep] = useState<Step>("read");

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-200 bg-accent-soft px-4 py-2.5">
        <p className="text-sm font-semibold text-amber-950">
          Sample receipt — illustrative, not from a real transaction
        </p>
        {step !== "read" ? (
          <button
            type="button"
            className="text-sm font-semibold text-brand underline"
            onClick={() => setStep("read")}
          >
            Start over
          </button>
        ) : null}
      </div>

      <div className="grid gap-5 p-4 sm:p-6 md:grid-cols-2">
        {/* The "paper" receipt */}
        <div
          className="rounded-lg border border-slate-200 bg-slate-50 p-4 font-mono text-xs leading-relaxed text-slate-800"
          aria-label="Sample paper receipt"
        >
          <p className="text-center text-sm font-bold">{SAMPLE.merchant}</p>
          <p className="text-center">{SAMPLE.address}</p>
          <p className="mt-2 flex justify-between">
            <span>{SAMPLE.date}</span>
            <span>#{SAMPLE.number}</span>
          </p>
          <hr className="my-2 border-dashed border-slate-400" />
          {SAMPLE.lines.map((l) => (
            <p key={l.description} className="flex justify-between gap-2">
              <span>
                {l.qty} × {l.description}
              </span>
              <span>{l.amount}</span>
            </p>
          ))}
          <hr className="my-2 border-dashed border-slate-400" />
          <p className="flex justify-between">
            <span>Subtotal</span>
            <span>{SAMPLE.subtotal}</span>
          </p>
          <p className="flex justify-between">
            <span>{SAMPLE.tax.label}</span>
            <span>{SAMPLE.tax.amount}</span>
          </p>
          <p className="flex justify-between font-bold">
            <span>TOTAL</span>
            <span>{SAMPLE.total}</span>
          </p>
        </div>

        {/* What TradeTrack shows */}
        <div className="space-y-3 text-sm">
          <p className="flex items-center gap-2 font-semibold text-ink">
            <PiSparkle className="h-5 w-5 text-brand" aria-hidden="true" />
            What TradeTrack reads
          </p>
          <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1.5">
            <dt className="text-slate-600">Merchant</dt>
            <dd className="font-medium">{SAMPLE.merchant}</dd>
            <dt className="text-slate-600">Date</dt>
            <dd className="font-medium">{SAMPLE.date}</dd>
            <dt className="text-slate-600">Subtotal</dt>
            <dd className="font-medium">{money(SAMPLE.subtotal)}</dd>
            <dt className="text-slate-600">Tax</dt>
            <dd className="font-medium">
              {SAMPLE.tax.label}: {money(SAMPLE.tax.amount)}
            </dd>
            <dt className="text-slate-600">Total</dt>
            <dd className="font-semibold">{money(SAMPLE.total)}</dd>
          </dl>

          <div className="rounded-lg border border-slate-200 p-3">
            <p className="text-slate-600">Suggested category</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-2 font-medium">
              {SAMPLE.category}
              {step === "read" ? (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900">
                  AI suggestion — please confirm
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-900">
                  <PiCheckCircle aria-hidden="true" /> Confirmed by you
                </span>
              )}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              You can always change the category. It is a suggestion, not tax advice.
            </p>
          </div>

          <div aria-live="polite">
            {step === "read" ? (
              <Button onClick={() => setStep("confirmed")}>1. Confirm the category</Button>
            ) : step === "confirmed" ? (
              <Button onClick={() => setStep("saved")}>2. Save receipt</Button>
            ) : (
              <p className="rounded-lg bg-emerald-50 p-3 font-medium text-emerald-950">
                Saved — in your own account this receipt would now appear in your dashboard, ready to
                export. (This is only a sample: nothing was stored.)
              </p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
