// Receipt history with search/filters, pagination and archive/delete.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { PiArchive, PiMagnifyingGlass, PiPlus, PiTrash } from "react-icons/pi";
import {
  apiErrorInfo,
  archiveReceipt,
  deleteReceipt,
  listReceipts,
  unarchiveReceipt,
  type Receipt,
  type ReceiptFilters,
} from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { formatDate, isDecimal, money } from "../lib/format";
import { Alert } from "./Alert";
import { Button, buttonClasses } from "./Button";
import { Card } from "./Card";
import { ConfirmDialog } from "./ConfirmDialog";
import { Input, Select } from "./Input";
import { PremiumLock } from "./PremiumLock";
import { PageSpinner } from "./Spinner";
import { AiBadge, StatusBadge } from "./StatusBadge";

const PAGE = 20;
const STATUSES = [
  { value: "", label: "Active (not archived)" },
  { value: "NEEDS_REVIEW", label: "Needs review" },
  { value: "SAVED", label: "Saved" },
  { value: "FAILED", label: "Extraction failed" },
  { value: "ARCHIVED", label: "Archived" },
];

export function ReceiptsTab({ goTo }: { goTo: (t: "plan") => void }) {
  const { user } = useAuth();
  const { data: config } = useConfig();
  const queryClient = useQueryClient();
  const premium = user?.plan === "PREMIUM";

  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [offset, setOffset] = useState(0);
  const [toDelete, setToDelete] = useState<Receipt | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const amountErr = (v: string) => (v && !isDecimal(v) ? "Use a number like 25.00" : null);
  const minErr = premium ? amountErr(minAmount) : null;
  const maxErr = premium ? amountErr(maxAmount) : null;

  const filters: ReceiptFilters = {
    q: debouncedQ,
    category,
    status,
    limit: PAGE,
    offset,
    ...(premium
      ? {
          date_from: dateFrom,
          date_to: dateTo,
          min_amount: minErr ? "" : minAmount,
          max_amount: maxErr ? "" : maxAmount,
        }
      : {}),
  };

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ["receipts", filters],
    queryFn: () => listReceipts(filters),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const resetPage = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setOffset(0);
  };

  async function act(r: Receipt, fn: () => Promise<unknown>) {
    setBusyId(r.id);
    setActionError(null);
    try {
      await fn();
      await queryClient.invalidateQueries({ queryKey: ["receipts"] });
      void queryClient.invalidateQueries({ queryKey: ["usage"] });
      void queryClient.removeQueries({ queryKey: ["receipt", r.id] });
    } catch (err) {
      setActionError(apiErrorInfo(err).message);
    } finally {
      setBusyId(null);
      setToDelete(null);
    }
  }

  const info = error ? apiErrorInfo(error) : null;
  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const filtered = Boolean(debouncedQ || category || status || dateFrom || dateTo || minAmount || maxAmount);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold text-ink">Your receipts</h2>
        <Link to="/" className={buttonClasses("primary", "sm")}>
          <PiPlus aria-hidden="true" /> Upload a receipt
        </Link>
      </div>

      <Card className="space-y-3 p-4">
        <form role="search" className="grid gap-3 sm:grid-cols-3" onSubmit={(e) => e.preventDefault()}>
          <div className="sm:col-span-3">
            <label htmlFor="rq" className="mb-1 block text-sm font-medium text-slate-800">
              Search merchant, items or receipt number
            </label>
            <div className="relative">
              <PiMagnifyingGlass className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-500" aria-hidden="true" />
              <input
                id="rq"
                type="search"
                value={q}
                onChange={(e) => resetPage(setQ)(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white py-2.5 pl-10 pr-3 text-base sm:text-sm"
                placeholder="e.g. Home Hardware"
              />
            </div>
          </div>
          <Select label="Category" value={category} onChange={(e) => resetPage(setCategory)(e.target.value)}>
            <option value="">All categories</option>
            {(config?.categories ?? []).map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
          <Select label="Status" value={status} onChange={(e) => resetPage(setStatus)(e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
          {premium ? (
            <>
              <Input label="From date" type="date" value={dateFrom} onChange={(e) => resetPage(setDateFrom)(e.target.value)} />
              <Input label="To date" type="date" value={dateTo} onChange={(e) => resetPage(setDateTo)(e.target.value)} />
              <span className="hidden sm:block" />
              <Input label="Min amount (CAD)" inputMode="decimal" value={minAmount} error={minErr} onChange={(e) => resetPage(setMinAmount)(e.target.value)} />
              <Input label="Max amount (CAD)" inputMode="decimal" value={maxAmount} error={maxErr} onChange={(e) => resetPage(setMaxAmount)(e.target.value)} />
            </>
          ) : null}
        </form>
        {!premium ? (
          <PremiumLock title="Date range and amount filters" onUpgrade={() => goTo("plan")}>
            Premium lets you filter by date range and by minimum or maximum amount. Search, category and
            status filters are free.
          </PremiumLock>
        ) : null}
      </Card>

      {actionError ? <Alert kind="error">{actionError}</Alert> : null}
      {info?.code === "premium_required" ? (
        <Alert kind="warning" title="Premium filter">
          {info.message} Clear the date and amount filters to see your receipts.
        </Alert>
      ) : info ? (
        <Alert kind="error" action={<Button size="sm" variant="secondary" onClick={() => void refetch()}>Try again</Button>}>
          {info.message}
        </Alert>
      ) : null}

      {isLoading ? (
        <PageSpinner label="Loading receipts…" />
      ) : !error && items.length === 0 ? (
        <Card className="p-8 text-center">
          <h3 className="font-semibold text-ink">{filtered ? "No receipts match these filters" : "No receipts yet"}</h3>
          <p className="mt-1 text-sm text-slate-600">
            {filtered
              ? "Try clearing a filter or searching for something else."
              : "Upload your first receipt and it will appear here."}
          </p>
          {!filtered ? (
            <Link to="/" className={buttonClasses("primary", "md", "mt-4")}>
              Upload a receipt
            </Link>
          ) : null}
        </Card>
      ) : (
        <>
          <ul className={`space-y-2 ${isFetching ? "opacity-70" : ""}`} aria-label="Receipts">
            {items.map((r) => (
              <li key={r.id}>
                <Card className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <Link to={`/receipts/${r.id}`} className="block break-words font-semibold text-brand hover:underline">
                      {r.merchant ?? "Merchant not available"}
                    </Link>
                    <p className="mt-0.5 text-sm text-slate-700">
                      {formatDate(r.receipt_date)} · {r.category ?? "No category"}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <StatusBadge status={r.processing_status} />
                      {r.category && r.category_is_ai_suggested ? <AiBadge /> : null}
                      {r.source === "EMAIL" ? (
                        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-800">Email</span>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-3 sm:justify-end">
                    <p className="text-base font-bold tabular-nums text-ink">{money(r.total, r.currency)}</p>
                    <div className="flex gap-1.5">
                      <Link to={`/receipts/${r.id}`} className={buttonClasses("secondary", "sm")}>
                        Open
                      </Link>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busyId === r.id}
                        aria-label={`${r.processing_status === "ARCHIVED" ? "Unarchive" : "Archive"} receipt ${r.merchant ?? r.id}`}
                        onClick={() => void act(r, () => (r.processing_status === "ARCHIVED" ? unarchiveReceipt(r.id) : archiveReceipt(r.id)))}
                      >
                        <PiArchive aria-hidden="true" />
                        <span className="hidden sm:inline">{r.processing_status === "ARCHIVED" ? "Unarchive" : "Archive"}</span>
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={busyId === r.id}
                        aria-label={`Delete receipt ${r.merchant ?? r.id}`}
                        onClick={() => setToDelete(r)}
                      >
                        <PiTrash aria-hidden="true" className="text-red-700" />
                      </Button>
                    </div>
                  </div>
                </Card>
              </li>
            ))}
          </ul>

          <nav aria-label="Pagination" className="flex items-center justify-between gap-2 text-sm text-slate-700">
            <p>
              Showing {total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                Previous
              </Button>
              <Button size="sm" variant="secondary" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
                Next
              </Button>
            </div>
          </nav>
        </>
      )}

      {toDelete ? (
        <ConfirmDialog
          title="Delete this receipt?"
          confirmLabel="Delete permanently"
          danger
          busy={busyId === toDelete.id}
          onCancel={() => setToDelete(null)}
          onConfirm={() => void act(toDelete, () => deleteReceipt(toDelete.id))}
        >
          {toDelete.merchant ?? toDelete.id} and its original file will be removed for good. Archive it
          instead if you only want it out of the way.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
