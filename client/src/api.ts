// Typed API client for the TradeTrack contract (docs/api.md). One axios instance with
// cookies enabled: auth is the httponly cookie, never localStorage. Money is always a
// string end to end; null means "unavailable" and is never replaced by a guess.
import axios from "axios";

export const http = axios.create({
  baseURL: "/api",
  withCredentials: true,
});

// A 401 on a private call tells the AuthProvider the session is gone.
export const UNAUTHORIZED_EVENT = "tradetrack:unauthorized";
http.interceptors.response.use(
  (r) => r,
  (err) => {
    const url: string = err?.config?.url ?? "";
    if (axios.isAxiosError(err) && err.response?.status === 401 && !/^\/(login|me)$/.test(url)) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    return Promise.reject(err);
  }
);

// ---------------------------------------------------------------- errors
export interface ApiErrorInfo {
  status: number | null;
  code: string | null;
  message: string;
  /** Extra fields from `detail` (receipt_id, fields, limit, used, period_end ...). */
  data: Record<string, unknown>;
}

/** Normalise FastAPI's `{detail: "text"}` / `{detail: {code, message}}` / pydantic arrays. */
export function parseErrorBody(status: number | null, body: unknown, fallback: string): ApiErrorInfo {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return { status, code: null, message: detail, data: {} };
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => {
      const loc = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
      return loc ? `${loc}: ${d?.msg ?? "invalid"}` : String(d?.msg ?? "invalid");
    });
    return { status, code: null, message: msgs.join("; ") || fallback, data: {} };
  }
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    return {
      status,
      code: typeof d.code === "string" ? d.code : null,
      message: typeof d.message === "string" ? d.message : fallback,
      data: d,
    };
  }
  return { status, code: null, message: fallback, data: {} };
}

export function apiErrorInfo(err: unknown, fallback = "Something went wrong. Please try again."): ApiErrorInfo {
  if (axios.isAxiosError(err)) {
    if (!err.response) {
      return {
        status: null,
        code: "network",
        message: "Can't reach TradeTrack right now. Check your connection and try again.",
        data: {},
      };
    }
    const info = parseErrorBody(err.response.status, err.response.data, fallback);
    if (info.message === fallback) {
      if (err.response.status === 413) info.message = "That file is too large.";
      if (err.response.status === 429) info.message = "Too many requests. Please wait a moment and try again.";
      if (err.response.status >= 500 && info.code === null) info.message = "TradeTrack had a problem. Please try again shortly.";
    }
    return info;
  }
  return { status: null, code: null, message: err instanceof Error ? err.message : fallback, data: {} };
}

export const apiError = (err: unknown, fallback?: string) => apiErrorInfo(err, fallback).message;

// ---------------------------------------------------------------- types
export type Plan = "FREE" | "PREMIUM";
export type TaxType = "GST" | "HST" | "PST" | "QST" | "OTHER";
export const TAX_TYPES: TaxType[] = ["GST", "HST", "PST", "QST", "OTHER"];

export interface PlanInfo {
  id: Plan;
  name: string;
  price_cad: string;
  monthly_receipt_limit: number | null;
  features: string[];
}

export interface AppConfig {
  app_name: string;
  currency: string;
  plans: PlanInfo[];
  feature_matrix: { feature: string; free: boolean; premium: boolean }[];
  categories: string[];
  provinces: { code: string; name: string; tax_hint: string }[];
  upload: { max_mb: number; allowed_types: string[] };
  services: {
    ai_configured: boolean;
    inbound_email_configured: boolean;
    inbound_domain: string | null;
    billing_mode: "stripe" | "demo";
    smtp_configured: boolean;
    file_storage: "s3" | "database";
  };
}

export interface User {
  id: string | number;
  email: string;
  first_name: string;
  last_name: string;
  business_name: string | null;
  province: string;
  accountant_email: string | null;
  gst_hst_registered: boolean | null;
  gst_hst_number: string | null;
  plan: Plan;
  subscription_status: string | null;
  forwarding_alias: string;
  forwarding_address: string | null;
  created_at: string;
}

export type ProcessingStatus = "NEEDS_REVIEW" | "SAVED" | "FAILED" | "ARCHIVED";
export type Confidence = "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";

export interface LineItem {
  description: string;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
}
export interface TaxLine {
  label: string;
  amount: string;
  tax_type: TaxType;
}
export interface ReceiptWarning {
  code: string;
  severity: "info" | "warning";
  field: string | null;
  message: string;
}

export interface Receipt {
  id: string;
  source: "UPLOAD" | "EMAIL";
  processing_status: ProcessingStatus;
  extraction_confidence: Confidence;
  extraction_error: string | null;
  original_filename: string | null;
  file_mime_type: string | null;
  has_original_file: boolean;
  is_sample: boolean;
  merchant: string | null;
  receipt_date: string | null;
  receipt_time: string | null;
  currency: string;
  receipt_number: string | null;
  line_items: LineItem[];
  discounts: string | null;
  subtotal: string | null;
  tax_lines: TaxLine[];
  tax_total: string | null;
  total: string | null;
  province: string | null;
  category: string | null;
  category_is_ai_suggested: boolean;
  warnings: ReceiptWarning[];
  notes: string | null;
  processing_note: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export type ReceiptPatch = Partial<
  Pick<
    Receipt,
    | "merchant"
    | "receipt_date"
    | "receipt_time"
    | "currency"
    | "receipt_number"
    | "line_items"
    | "discounts"
    | "subtotal"
    | "tax_lines"
    | "tax_total"
    | "total"
    | "province"
    | "category"
    | "notes"
  >
>;

export interface ReceiptFilters {
  q?: string;
  category?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  min_amount?: string;
  max_amount?: string;
  limit?: number;
  offset?: number;
}

export interface Usage {
  plan: Plan;
  saved_this_period: number;
  limit: number | null;
  remaining: number | null;
  period_start: string;
  period_end: string;
  period_label: string;
  resets_on: string;
}

export interface Summary {
  month: string;
  currency: string;
  count: number;
  undated_count: number;
  subtotal: string;
  tax_total: string;
  total: string;
  by_category: { category: string; count: number; subtotal: string; tax_total: string; total: string }[];
  by_tax_type: Record<string, string>;
  flagged_count: number;
}

export interface BillingStatus {
  plan: Plan;
  subscription_status: string | null;
  mode: "stripe" | "demo";
  can_manage: boolean;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export interface InboundLogEntry {
  id: string | number;
  received_at: string;
  status: "PROCESSED" | "REJECTED" | "DUPLICATE" | "FAILED";
  reason: string | null;
  attachments: number;
  receipt_ids: string[];
}

export interface ExportParams {
  format: "csv" | "json";
  month?: string;
  date_from?: string;
  date_to?: string;
  category?: string;
}

// ---------------------------------------------------------------- public
export async function getConfig(): Promise<AppConfig> {
  return (await http.get<AppConfig>("/config")).data;
}

// ---------------------------------------------------------------- account
export interface RegisterBody {
  email: string;
  first_name: string;
  last_name: string;
  password: string;
  business_name?: string;
  province?: string;
  accountant_email?: string;
}

/** Registration also signs the user in (the server sets the cookie). */
export async function register(body: RegisterBody): Promise<User> {
  return (await http.post<User>("/register", body)).data;
}

export async function login(email: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username: email, password });
  await http.post("/login", form, { headers: { "Content-Type": "application/x-www-form-urlencoded" } });
}

export async function logout(): Promise<void> {
  await http.post("/logout");
}

export async function getMe(): Promise<User> {
  return (await http.get<User>("/me")).data;
}

export type ProfilePatch = Partial<
  Pick<
    User,
    | "first_name"
    | "last_name"
    | "business_name"
    | "province"
    | "accountant_email"
    | "gst_hst_registered"
    | "gst_hst_number"
  >
>;

export async function updateMe(body: ProfilePatch): Promise<User> {
  return (await http.put<User>("/me", body)).data;
}

export async function rotateForwardingAlias(): Promise<User> {
  return (await http.post<User>("/me/forwarding-alias/rotate")).data;
}

export async function getInboundLog(): Promise<InboundLogEntry[]> {
  return (await http.get<InboundLogEntry[]>("/me/inbound-log")).data;
}

export async function deleteAccount(password: string): Promise<void> {
  await http.delete("/me", { data: { password } });
}

// ---------------------------------------------------------------- receipts
/** Upload a receipt for AI extraction. Slow (the AI call), so the timeout is generous. */
export async function processReceipt(file: File): Promise<Receipt> {
  const form = new FormData();
  form.append("file", file);
  return (await http.post<Receipt>("/receipts/process", form, { timeout: 120_000 })).data;
}

export async function reprocessReceipt(id: string): Promise<Receipt> {
  return (await http.post<Receipt>(`/receipts/${id}/reprocess`, null, { timeout: 120_000 })).data;
}

export async function getReceipt(id: string): Promise<Receipt> {
  return (await http.get<Receipt>(`/receipts/${encodeURIComponent(id)}`)).data;
}

export async function updateReceipt(id: string, body: ReceiptPatch): Promise<Receipt> {
  return (await http.patch<Receipt>(`/receipts/${id}`, body)).data;
}

export async function saveReceipt(id: string): Promise<Receipt> {
  return (await http.post<Receipt>(`/receipts/${id}/save`)).data;
}

export async function archiveReceipt(id: string): Promise<Receipt> {
  return (await http.post<Receipt>(`/receipts/${id}/archive`)).data;
}

export async function unarchiveReceipt(id: string): Promise<Receipt> {
  return (await http.post<Receipt>(`/receipts/${id}/unarchive`)).data;
}

export async function deleteReceipt(id: string): Promise<void> {
  await http.delete(`/receipts/${id}`);
}

/** The original upload as a blob, for the inline preview (the file is never public). */
export async function getReceiptFile(id: string): Promise<Blob> {
  return (await http.get<Blob>(`/receipts/${id}/file`, { responseType: "blob" })).data;
}

export async function listReceipts(f: ReceiptFilters = {}): Promise<{ items: Receipt[]; total: number }> {
  const params: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(f)) {
    if (v !== undefined && v !== "") params[k] = v;
  }
  return (await http.get<{ items: Receipt[]; total: number }>("/receipts", { params })).data;
}

export async function getUsage(): Promise<Usage> {
  return (await http.get<Usage>("/receipts/usage")).data;
}

export async function getSummary(month: string): Promise<Summary> {
  return (await http.get<Summary>("/receipts/summary", { params: { month } })).data;
}

export async function emailAccountant(month: string): Promise<{ detail?: string }> {
  return (await http.post<{ detail?: string }>("/receipts/export/email", { month })).data;
}

// Download URLs (fetched with lib/download.ts so errors show as messages).
export const receiptFileUrl = (id: string) => `/api/receipts/${id}/file`;
export const receiptPdfUrl = (id: string) => `/api/receipts/${id}/pdf`;
export const accountExportUrl = () => "/api/me/export";

export function exportUrl(p: ExportParams): string {
  const q = new URLSearchParams({ format: p.format });
  for (const k of ["month", "date_from", "date_to", "category"] as const) {
    if (p[k]) q.set(k, p[k]!);
  }
  return `/api/receipts/export?${q.toString()}`;
}

export const summaryDownloadUrl = (month: string, format: "csv" | "pdf") =>
  `/api/receipts/export/summary?month=${encodeURIComponent(month)}&format=${format}`;

// ---------------------------------------------------------------- billing
export async function getBillingStatus(): Promise<BillingStatus> {
  return (await http.get<BillingStatus>("/billing/status")).data;
}
export async function startCheckout(): Promise<{ url: string }> {
  return (await http.post<{ url: string }>("/billing/checkout")).data;
}
export async function openBillingPortal(): Promise<{ url: string }> {
  return (await http.post<{ url: string }>("/billing/portal")).data;
}
export async function demoUpgrade(): Promise<void> {
  await http.post("/billing/demo/upgrade");
}
export async function demoDowngrade(): Promise<void> {
  await http.post("/billing/demo/downgrade");
}
