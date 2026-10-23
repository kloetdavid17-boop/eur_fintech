// Read-only view of an extracted receipt. null is always shown as "Not available".
import type { AppConfig, Receipt } from "../api";
import { formatDate, money, NOT_AVAILABLE } from "../lib/format";
import { Card } from "./Card";
import { AiBadge, ConfidenceBadge } from "./StatusBadge";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-x-3 py-1.5 sm:grid-cols-[9rem_1fr]">
      <dt className="text-sm text-slate-600">{label}</dt>
      <dd className="min-w-0 break-words text-sm font-medium text-slate-900">{children}</dd>
    </div>
  );
}

const na = (v: string | null | undefined) => (v && v.trim() ? v : <span className="font-normal text-slate-600">{NOT_AVAILABLE}</span>);

export function ReceiptSummary({ receipt: r, config }: { receipt: Receipt; config: AppConfig | undefined }) {
  const province = config?.provinces.find((p) => p.code === r.province);
  const when = r.receipt_date
    ? `${formatDate(r.receipt_date)}${r.receipt_time ? `, ${r.receipt_time}` : ""}`
    : null;
  const cur = r.currency || "CAD";

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <dl className="divide-y divide-slate-100">
          <Row label="Merchant">{na(r.merchant)}</Row>
          <Row label="Date and time">{na(when)}</Row>
          <Row label="Currency">{cur}</Row>
          <Row label="Receipt number">{na(r.receipt_number)}</Row>
          <Row label="Province">{na(province ? `${province.name} (${r.province})` : r.province)}</Row>
          <Row label="Confidence">
            <ConfidenceBadge value={r.extraction_confidence} />
          </Row>
          <Row label="Source">{r.source === "EMAIL" ? "Forwarded email" : "Upload"}</Row>
        </dl>
      </Card>

      <Card className="p-4">
        <h3 className="font-semibold text-ink">Suggested expense category</h3>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm font-medium">
          {na(r.category)}
          {r.category && r.category_is_ai_suggested ? <AiBadge /> : null}
        </p>
        <p className="mt-1 text-xs text-slate-600">
          {r.category_is_ai_suggested
            ? "This category is an AI suggestion. Change it or confirm it when you save."
            : "You've reviewed this category."}{" "}
          Categories and tax details are suggestions, not tax advice. Check with your accountant before
          claiming anything.
        </p>
      </Card>

      <Card className="p-4">
        <h3 className="font-semibold text-ink">Line items</h3>
        {r.line_items.length === 0 ? (
          <p className="mt-1 text-sm text-slate-600">No line items were read from this receipt.</p>
        ) : (
          <ul className="mt-2 divide-y divide-slate-100">
            {r.line_items.map((l, i) => (
              <li key={i} className="flex items-start justify-between gap-3 py-2 text-sm">
                <div className="min-w-0">
                  <p className="break-words font-medium text-slate-900">{l.description}</p>
                  <p className="text-xs text-slate-600">
                    Qty {l.quantity ?? NOT_AVAILABLE}
                    {" · "}Unit {l.unit_price ? money(l.unit_price, cur) : NOT_AVAILABLE}
                  </p>
                </div>
                <p className="shrink-0 font-medium tabular-nums">{money(l.amount, cur)}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-4">
        <h3 className="font-semibold text-ink">Totals</h3>
        <dl className="mt-2 space-y-1.5 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-slate-700">Subtotal</dt>
            <dd className="tabular-nums">{money(r.subtotal, cur)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-slate-700">Discounts</dt>
            <dd className="tabular-nums">{money(r.discounts, cur)}</dd>
          </div>
          {r.tax_lines.length === 0 ? (
            <div className="flex justify-between gap-3">
              <dt className="text-slate-700">Tax lines</dt>
              <dd className="text-slate-600">{NOT_AVAILABLE}</dd>
            </div>
          ) : (
            r.tax_lines.map((t, i) => (
              <div key={i} className="flex justify-between gap-3">
                <dt className="text-slate-700">
                  {t.label} <span className="text-xs text-slate-600">({t.tax_type})</span>
                </dt>
                <dd className="tabular-nums">{money(t.amount, cur)}</dd>
              </div>
            ))
          )}
          <div className="flex justify-between gap-3">
            <dt className="text-slate-700">Tax total</dt>
            <dd className="tabular-nums">{money(r.tax_total, cur)}</dd>
          </div>
          <div className="flex justify-between gap-3 border-t border-slate-200 pt-2 text-base font-bold">
            <dt>Total</dt>
            <dd className="tabular-nums">{money(r.total, cur)}</dd>
          </div>
        </dl>
      </Card>

      {r.notes ? (
        <Card className="p-4">
          <h3 className="font-semibold text-ink">Your notes</h3>
          <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-800">{r.notes}</p>
        </Card>
      ) : null}
    </div>
  );
}
