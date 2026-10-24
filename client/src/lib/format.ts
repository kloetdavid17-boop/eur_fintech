// Formatting and validation helpers. Money arrives as decimal strings and stays strings;
// we only convert to a number to *display* it. null/undefined is "Not available", never 0.

export const NOT_AVAILABLE = "Not available";

export function money(amount: string | number | null | undefined, currency = "CAD"): string {
  if (amount === null || amount === undefined || amount === "") return NOT_AVAILABLE;
  const n = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(n)) return NOT_AVAILABLE;
  try {
    return new Intl.NumberFormat("en-CA", { style: "currency", currency }).format(n);
  } catch {
    return `${currency} ${n.toFixed(2)}`;
  }
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Dates are shown as e.g. "Sep 18, 2026". Date-only strings are not shifted by time zone. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return NOT_AVAILABLE;
  const m = DATE_ONLY.exec(value);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
  if (Number.isNaN(d.getTime())) return NOT_AVAILABLE;
  return d.toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return NOT_AVAILABLE;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return NOT_AVAILABLE;
  return d.toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function isValidDate(s: string): boolean {
  const m = DATE_ONLY.exec(s);
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(y, mo - 1, d);
  return dt.getFullYear() === y && dt.getMonth() === mo - 1 && dt.getDate() === d;
}

export const isValidTime = (s: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(s);
/** Non-negative decimal with at most `dp` decimal places. */
export const isDecimal = (s: string, dp = 2) => new RegExp(`^\\d{1,8}(\\.\\d{1,${dp}})?$`).test(s);
export const isEmail = (s: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);

/** "YYYY-MM" for today, in the browser's time zone. */
export function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function monthLabel(month: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(month);
  if (!m) return month;
  return new Date(Number(m[1]), Number(m[2]) - 1, 1).toLocaleDateString("en-CA", {
    year: "numeric",
    month: "long",
  });
}

export type PeriodKind = "month" | "quarter" | "year" | "custom";

export interface PeriodChoice {
  kind: PeriodKind;
  month: string; // YYYY-MM
  year: string; // YYYY
  quarter: string; // 1-4
  from: string; // YYYY-MM-DD (custom)
  to: string; // YYYY-MM-DD (custom)
}

const pad = (n: number) => String(n).padStart(2, "0");
const lastDay = (y: number, m: number) => new Date(y, m, 0).getDate(); // m is 1-12

export function defaultPeriodChoice(): PeriodChoice {
  const d = new Date();
  return {
    kind: "month",
    month: currentMonth(),
    year: String(d.getFullYear()),
    quarter: String(Math.floor(d.getMonth() / 3) + 1),
    from: "",
    to: "",
  };
}

/** The API parameters for a choice, or null while the choice is incomplete or invalid. */
export function periodParams(c: PeriodChoice): { month?: string; date_from?: string; date_to?: string } | null {
  if (c.kind === "month") return /^\d{4}-(0[1-9]|1[0-2])$/.test(c.month) ? { month: c.month } : null;
  if (c.kind === "custom") {
    if (!c.from || !c.to || c.from > c.to) return null;
    return { date_from: c.from, date_to: c.to };
  }
  const y = Number(c.year);
  if (!/^\d{4}$/.test(c.year) || y < 2000 || y > 2100) return null;
  if (c.kind === "year") return { date_from: `${y}-01-01`, date_to: `${y}-12-31` };
  const q = Number(c.quarter);
  if (![1, 2, 3, 4].includes(q)) return null;
  const startM = (q - 1) * 3 + 1;
  const endM = startM + 2;
  return { date_from: `${y}-${pad(startM)}-01`, date_to: `${y}-${pad(endM)}-${pad(lastDay(y, endM))}` };
}

/** Human label for a summary label from the API: "October 2026" or "2026-07-01 to 2026-09-30". */
export function periodLabel(label: string): string {
  return /^\d{4}-\d{2}$/.test(label) ? monthLabel(label) : label;
}
