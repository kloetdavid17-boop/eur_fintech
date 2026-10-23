// Edit form for every receipt field. Money stays a string; blank means "unavailable"
// (null). Client checks are quick feedback only: the server validates again (422).
import { useState } from "react";
import { PiPlus, PiTrash } from "react-icons/pi";
import {
  TAX_TYPES,
  type AppConfig,
  type Receipt,
  type ReceiptPatch,
  type TaxType,
} from "../api";
import { isDecimal, isValidDate, isValidTime } from "../lib/format";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { Card } from "./Card";
import { Input, Select, Textarea } from "./Input";
import { Spinner } from "./Spinner";

interface LineForm {
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
}
interface TaxForm {
  label: string;
  amount: string;
  tax_type: TaxType;
}
export interface FormState {
  merchant: string;
  receipt_date: string;
  receipt_time: string;
  currency: string;
  receipt_number: string;
  province: string;
  category: string;
  notes: string;
  discounts: string;
  subtotal: string;
  tax_total: string;
  total: string;
  line_items: LineForm[];
  tax_lines: TaxForm[];
}

const s = (v: string | null | undefined) => v ?? "";
const orNull = (v: string) => (v.trim() === "" ? null : v.trim());

export function toForm(r: Receipt): FormState {
  return {
    merchant: s(r.merchant),
    receipt_date: s(r.receipt_date),
    receipt_time: s(r.receipt_time),
    currency: r.currency || "CAD",
    receipt_number: s(r.receipt_number),
    province: s(r.province),
    category: s(r.category),
    notes: s(r.notes),
    discounts: s(r.discounts),
    subtotal: s(r.subtotal),
    tax_total: s(r.tax_total),
    total: s(r.total),
    line_items: r.line_items.map((l) => ({
      description: l.description,
      quantity: s(l.quantity),
      unit_price: s(l.unit_price),
      amount: s(l.amount),
    })),
    tax_lines: r.tax_lines.map((t) => ({ label: t.label, amount: t.amount, tax_type: t.tax_type })),
  };
}

const blankLine = (l: LineForm) => !l.description.trim() && !l.quantity.trim() && !l.unit_price.trim() && !l.amount.trim();
const blankTax = (t: TaxForm) => !t.label.trim() && !t.amount.trim();

export function toPatch(f: FormState): ReceiptPatch {
  return {
    merchant: orNull(f.merchant),
    receipt_date: orNull(f.receipt_date),
    receipt_time: orNull(f.receipt_time),
    currency: f.currency.trim().toUpperCase() || "CAD",
    receipt_number: orNull(f.receipt_number),
    province: orNull(f.province),
    category: orNull(f.category),
    notes: orNull(f.notes),
    discounts: orNull(f.discounts),
    subtotal: orNull(f.subtotal),
    tax_total: orNull(f.tax_total),
    total: orNull(f.total),
    line_items: f.line_items
      .filter((l) => !blankLine(l))
      .map((l) => ({
        description: l.description.trim(),
        quantity: orNull(l.quantity),
        unit_price: orNull(l.unit_price),
        amount: orNull(l.amount),
      })),
    tax_lines: f.tax_lines
      .filter((t) => !blankTax(t))
      .map((t) => ({ label: t.label.trim(), amount: t.amount.trim(), tax_type: t.tax_type })),
  };
}

export function validate(f: FormState, categories: string[] | undefined): Record<string, string> {
  const e: Record<string, string> = {};
  const money = (key: string, v: string, label: string) => {
    if (v.trim() && !isDecimal(v.trim(), 2)) e[key] = `${label} must be a number like 12.50 (no minus sign or symbols).`;
  };
  if (f.receipt_date.trim() && !isValidDate(f.receipt_date.trim()))
    e.receipt_date = "Use a real date in the format YYYY-MM-DD.";
  if (f.receipt_time.trim() && !isValidTime(f.receipt_time.trim())) e.receipt_time = "Use 24-hour time like 14:35.";
  if (!/^[A-Za-z]{3}$/.test(f.currency.trim())) e.currency = "Use a 3-letter currency code such as CAD.";
  if (f.category && categories && categories.length && !categories.includes(f.category))
    e.category = "Choose one of the listed categories.";
  money("discounts", f.discounts, "Discounts");
  money("subtotal", f.subtotal, "Subtotal");
  money("tax_total", f.tax_total, "Tax total");
  money("total", f.total, "Total");
  f.line_items.forEach((l, i) => {
    if (blankLine(l)) return;
    if (!l.description.trim()) e[`li.${i}.description`] = "Describe the item.";
    if (l.quantity.trim() && !isDecimal(l.quantity.trim(), 4)) e[`li.${i}.quantity`] = "Quantity must be a positive number.";
    if (l.unit_price.trim() && !isDecimal(l.unit_price.trim(), 4)) e[`li.${i}.unit_price`] = "Use a number like 4.28.";
    if (l.amount.trim() && !isDecimal(l.amount.trim(), 2)) e[`li.${i}.amount`] = "Use a number like 85.60.";
  });
  f.tax_lines.forEach((t, i) => {
    if (blankTax(t)) return;
    if (!t.label.trim()) e[`tl.${i}.label`] = "Add a label, e.g. HST 13%.";
    if (!t.amount.trim()) e[`tl.${i}.amount`] = "Enter the tax amount.";
    else if (!isDecimal(t.amount.trim(), 2)) e[`tl.${i}.amount`] = "Use a number like 19.90.";
  });
  return e;
}

export function ReceiptForm({
  receipt,
  config,
  serverErrors,
  serverMessage,
  busy,
  onSubmit,
  onCancel,
}: {
  receipt: Receipt;
  config: AppConfig | undefined;
  /** Per-field messages from the server (e.g. missing_required_fields). */
  serverErrors: Record<string, string>;
  serverMessage: string | null;
  busy: boolean;
  onSubmit: (patch: ReceiptPatch, confirmAfter: boolean) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState<FormState>(() => toForm(receipt));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const all = { ...serverErrors, ...errors };
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  const text = (k: keyof FormState) => (ev: { target: { value: string } }) => set(k, ev.target.value as never);
  const needsConfirm = receipt.processing_status !== "SAVED";

  const categories = config?.categories ?? [];
  const categoryOptions = f.category && !categories.includes(f.category) ? [f.category, ...categories] : categories;

  function submit(confirmAfter: boolean) {
    const found = validate(f, config?.categories);
    setErrors(found);
    if (Object.keys(found).length) {
      requestAnimationFrame(() => document.querySelector<HTMLElement>("[aria-invalid='true']")?.focus());
      return;
    }
    onSubmit(toPatch(f), confirmAfter);
  }

  const lineSet = (i: number, k: keyof LineForm, v: string) =>
    set("line_items", f.line_items.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const taxSet = <K extends keyof TaxForm>(i: number, k: K, v: TaxForm[K]) =>
    set("tax_lines", f.tax_lines.map((t, j) => (j === i ? { ...t, [k]: v } : t)));

  return (
    <form
      className="space-y-5"
      noValidate
      onSubmit={(ev) => {
        ev.preventDefault();
        submit(needsConfirm);
      }}
    >
      {Object.keys(errors).length ? (
        <Alert kind="error" title="Please fix the highlighted fields">
          Nothing has been changed yet.
        </Alert>
      ) : null}
      {serverMessage ? (
        <Alert kind="error" title="The server couldn't accept these changes">
          {serverMessage}
        </Alert>
      ) : null}
      <p className="text-sm text-slate-700">
        Leave a field blank if it isn't on the receipt. Blank fields are saved as "Not available", never
        guessed.
      </p>

      <Card className="space-y-4 p-4">
        <h3 className="font-semibold text-ink">Receipt details</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Merchant" value={f.merchant} onChange={text("merchant")} error={all.merchant} autoComplete="off" />
          <Input label="Receipt number" value={f.receipt_number} onChange={text("receipt_number")} error={all.receipt_number} autoComplete="off" />
          <Input label="Date" placeholder="YYYY-MM-DD" inputMode="numeric" value={f.receipt_date} onChange={text("receipt_date")} error={all.receipt_date} />
          <Input label="Time (24-hour)" placeholder="HH:MM" inputMode="numeric" value={f.receipt_time} onChange={text("receipt_time")} error={all.receipt_time} />
          <Input label="Currency" maxLength={3} value={f.currency} onChange={text("currency")} error={all.currency} />
          <Select label="Province or territory" value={f.province} onChange={text("province")} error={all.province}>
            <option value="">Not available</option>
            {(config?.provinces ?? []).map((p) => (
              <option key={p.code} value={p.code}>
                {p.name}
              </option>
            ))}
          </Select>
        </div>
        <Select
          label="Expense category"
          hint="A suggestion only. Choose what fits; this is not tax advice."
          value={f.category}
          onChange={text("category")}
          error={all.category}
        >
          <option value="">Not selected</option>
          {categoryOptions.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </Select>
      </Card>

      <Card className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-semibold text-ink">Line items</h3>
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              set("line_items", [...f.line_items, { description: "", quantity: "", unit_price: "", amount: "" }])
            }
          >
            <PiPlus aria-hidden="true" /> Add item
          </Button>
        </div>
        {f.line_items.length === 0 ? <p className="text-sm text-slate-600">No line items. Add one if you want them recorded.</p> : null}
        {f.line_items.map((l, i) => (
          <fieldset key={i} className="space-y-3 rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-xs font-semibold text-slate-700">Item {i + 1}</legend>
            <Input label="Description" value={l.description} onChange={(ev) => lineSet(i, "description", ev.target.value)} error={all[`li.${i}.description`]} />
            <div className="grid grid-cols-3 gap-3">
              <Input label="Qty" inputMode="decimal" value={l.quantity} onChange={(ev) => lineSet(i, "quantity", ev.target.value)} error={all[`li.${i}.quantity`]} />
              <Input label="Unit price" inputMode="decimal" value={l.unit_price} onChange={(ev) => lineSet(i, "unit_price", ev.target.value)} error={all[`li.${i}.unit_price`]} />
              <Input label="Amount" inputMode="decimal" value={l.amount} onChange={(ev) => lineSet(i, "amount", ev.target.value)} error={all[`li.${i}.amount`]} />
            </div>
            <Button size="sm" variant="ghost" onClick={() => set("line_items", f.line_items.filter((_, j) => j !== i))}>
              <PiTrash aria-hidden="true" /> Remove item {i + 1}
            </Button>
          </fieldset>
        ))}
      </Card>

      <Card className="space-y-4 p-4">
        <h3 className="font-semibold text-ink">Amounts and tax</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Subtotal" inputMode="decimal" value={f.subtotal} onChange={text("subtotal")} error={all.subtotal} />
          <Input label="Discounts" inputMode="decimal" value={f.discounts} onChange={text("discounts")} error={all.discounts} />
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-slate-800">Tax lines (as printed on the receipt)</p>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => set("tax_lines", [...f.tax_lines, { label: "", amount: "", tax_type: "GST" }])}
            >
              <PiPlus aria-hidden="true" /> Add tax line
            </Button>
          </div>
          {f.tax_lines.length === 0 ? <p className="text-sm text-slate-600">No tax lines recorded.</p> : null}
          {f.tax_lines.map((t, i) => (
            <fieldset key={i} className="space-y-3 rounded-lg border border-slate-200 p-3">
              <legend className="px-1 text-xs font-semibold text-slate-700">Tax line {i + 1}</legend>
              <div className="grid gap-3 sm:grid-cols-3">
                <Select label="Tax type" value={t.tax_type} onChange={(ev) => taxSet(i, "tax_type", ev.target.value as TaxType)}>
                  {TAX_TYPES.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </Select>
                <Input label="Label" placeholder="HST 13%" value={t.label} onChange={(ev) => taxSet(i, "label", ev.target.value)} error={all[`tl.${i}.label`]} />
                <Input label="Amount" inputMode="decimal" value={t.amount} onChange={(ev) => taxSet(i, "amount", ev.target.value)} error={all[`tl.${i}.amount`]} />
              </div>
              <Button size="sm" variant="ghost" onClick={() => set("tax_lines", f.tax_lines.filter((_, j) => j !== i))}>
                <PiTrash aria-hidden="true" /> Remove tax line {i + 1}
              </Button>
            </fieldset>
          ))}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Tax total" inputMode="decimal" value={f.tax_total} onChange={text("tax_total")} error={all.tax_total} />
          <Input label="Total" inputMode="decimal" value={f.total} onChange={text("total")} error={all.total} />
        </div>
      </Card>

      <Card className="p-4">
        <Textarea label="Your notes (optional)" rows={3} value={f.notes} onChange={text("notes")} error={all.notes} />
      </Card>

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:flex-wrap">
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        {needsConfirm ? (
          <Button variant="secondary" onClick={() => submit(false)} disabled={busy}>
            Save draft changes
          </Button>
        ) : null}
        <Button type="submit" disabled={busy}>
          {busy ? <Spinner label="Saving…" /> : needsConfirm ? "Save and confirm receipt" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
