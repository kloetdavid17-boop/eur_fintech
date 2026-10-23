// Page 2: receipt detail + results. Review, correct, confirm and save one receipt.
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PiArrowLeft,
  PiArchive,
  PiArrowCounterClockwise,
  PiCheckCircle,
  PiDownloadSimple,
  PiFilePdf,
  PiPencilSimple,
  PiTrash,
} from "react-icons/pi";
import {
  apiErrorInfo,
  archiveReceipt,
  deleteReceipt,
  getReceipt,
  receiptFileUrl,
  receiptPdfUrl,
  reprocessReceipt,
  saveReceipt,
  unarchiveReceipt,
  updateReceipt,
  type Receipt,
  type ReceiptPatch,
} from "../api";
import { Alert } from "../components/Alert";
import { Button, buttonClasses } from "../components/Button";
import { Card } from "../components/Card";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FilePreview } from "../components/FilePreview";
import { ReceiptForm } from "../components/ReceiptForm";
import { ReceiptSummary } from "../components/ReceiptSummary";
import { PageSpinner, Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { useConfig } from "../hooks/useConfig";
import { downloadFile } from "../lib/download";
import { formatDate, formatDateTime } from "../lib/format";

type Busy = null | "save" | "archive" | "delete" | "reprocess" | "download";
interface LimitInfo {
  message: string;
  limit?: number;
  used?: number;
  period_end?: string;
}

export function ReceiptDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { data: config } = useConfig();

  const { data: receipt, isLoading, error } = useQuery({
    queryKey: ["receipt", id],
    queryFn: () => getReceipt(id),
    retry: false,
  });

  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [limit, setLimit] = useState<LimitInfo | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | "delete" | "reprocess">(null);
  const autoEdited = useRef<string | null>(null);

  const notice = (location.state as { notice?: string } | null)?.notice ?? null;

  // A FAILED receipt has nothing to confirm yet: open the form so it can be completed by hand.
  useEffect(() => {
    if (receipt && receipt.processing_status === "FAILED" && autoEdited.current !== receipt.id) {
      autoEdited.current = receipt.id;
      setEditing(true);
    }
  }, [receipt]);

  function clearFeedback() {
    setSuccess(null);
    setProblem(null);
    setLimit(null);
    setFieldErrors({});
    setFormMessage(null);
  }

  function store(r: Receipt) {
    queryClient.setQueryData(["receipt", id], r);
    void queryClient.invalidateQueries({ queryKey: ["receipts"] });
    void queryClient.invalidateQueries({ queryKey: ["usage"] });
  }

  /** Optionally PATCH, then confirm via POST /save. */
  async function saveFlow(patch: ReceiptPatch | null, confirmAfter: boolean) {
    if (!receipt) return;
    clearFeedback();
    setBusy("save");
    let current = receipt;
    try {
      if (patch) {
        current = await updateReceipt(id, patch);
        store(current);
      } else if (confirmAfter && current.category && current.category_is_ai_suggested) {
        // Saving confirms the category the user has just looked at.
        current = await updateReceipt(id, { category: current.category });
        store(current);
      }
      if (!confirmAfter) {
        setEditing(false);
        setSuccess("Your changes were saved. The receipt still needs to be confirmed.");
        return;
      }
      current = await saveReceipt(id);
      store(current);
      setEditing(false);
      setSuccess("Receipt saved. It now counts toward this month's allowance and appears in your dashboard.");
    } catch (err) {
      const info = apiErrorInfo(err);
      if (info.status === 402 && info.code === "free_limit_reached") {
        setLimit({
          message: info.message,
          limit: typeof info.data.limit === "number" ? info.data.limit : undefined,
          used: typeof info.data.used === "number" ? info.data.used : undefined,
          period_end: typeof info.data.period_end === "string" ? info.data.period_end : undefined,
        });
        setEditing(false);
      } else if (info.status === 422 && info.code === "missing_required_fields") {
        const fields = Array.isArray(info.data.fields) ? (info.data.fields as string[]) : [];
        const errs: Record<string, string> = {};
        fields.forEach((f) => (errs[f] = "Required before this receipt can be saved."));
        setFieldErrors(errs);
        setFormMessage(info.message);
        setProblem(
          `${info.message}${fields.length ? ` Missing: ${fields.join(", ")}.` : ""}`
        );
        setEditing(true);
      } else if (info.status === 422) {
        setFormMessage(info.message);
        setEditing(true);
      } else {
        setProblem(info.message);
      }
    } finally {
      setBusy(null);
    }
  }

  async function simple(kind: Busy, fn: () => Promise<Receipt | void>, ok: string) {
    clearFeedback();
    setBusy(kind);
    try {
      const r = await fn();
      if (r) store(r);
      setSuccess(ok);
    } catch (err) {
      setProblem(apiErrorInfo(err).message);
    } finally {
      setBusy(null);
    }
  }

  async function doDelete() {
    setBusy("delete");
    try {
      await deleteReceipt(id);
      queryClient.removeQueries({ queryKey: ["receipt", id] });
      void queryClient.invalidateQueries({ queryKey: ["receipts"] });
      void queryClient.invalidateQueries({ queryKey: ["usage"] });
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setConfirm(null);
      setProblem(apiErrorInfo(err).message);
      setBusy(null);
    }
  }

  async function doReprocess() {
    setConfirm(null);
    clearFeedback();
    setBusy("reprocess");
    try {
      store(await reprocessReceipt(id));
      setEditing(false);
      setSuccess("The receipt was read again. Please review the new results.");
    } catch (err) {
      const info = apiErrorInfo(err);
      void queryClient.invalidateQueries({ queryKey: ["receipt", id] });
      setProblem(
        info.code === "ai_not_configured"
          ? `${info.message} Receipt reading isn't set up on this server, so you can complete the fields by hand.`
          : info.message
      );
      setEditing(true);
    } finally {
      setBusy(null);
    }
  }

  async function download(url: string, fallback: string) {
    clearFeedback();
    setBusy("download");
    try {
      await downloadFile(url, fallback);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "The download failed.");
    } finally {
      setBusy(null);
    }
  }

  if (isLoading) return <PageSpinner label="Loading receipt…" />;
  if (error || !receipt) {
    const info = apiErrorInfo(error, "We couldn't load this receipt.");
    return (
      <div className="space-y-4">
        <Alert kind="error" title={info.status === 404 ? "Receipt not found" : "Couldn't load the receipt"}>
          {info.status === 404
            ? "This receipt doesn't exist, or it belongs to a different account."
            : info.message}
        </Alert>
        <Link to="/dashboard" className={buttonClasses("secondary")}>
          <PiArrowLeft aria-hidden="true" /> Back to dashboard
        </Link>
      </div>
    );
  }

  const r = receipt;
  const canConfirm = r.processing_status === "NEEDS_REVIEW" || r.processing_status === "FAILED";
  const archived = r.processing_status === "ARCHIVED";
  const working = busy !== null;
  const warnings = [...r.warnings].sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "warning" ? -1 : 1));

  return (
    <div className="space-y-5">
      <Link to="/dashboard" className="inline-flex items-center gap-1 text-sm font-semibold text-brand hover:underline">
        <PiArrowLeft aria-hidden="true" /> Back to dashboard
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="break-words text-2xl font-extrabold text-ink">{r.merchant ?? "Receipt"}</h1>
          <p className="mt-0.5 text-sm text-slate-600">
            {r.id} · added {formatDateTime(r.created_at)}
            {r.reviewed_at ? ` · confirmed ${formatDate(r.reviewed_at)}` : ""}
          </p>
        </div>
        <StatusBadge status={r.processing_status} />
      </header>

      <div aria-live="polite" className="space-y-3">
        {success ? (
          <Alert kind="success" title="Done" action={
            <Link to="/dashboard" className="text-sm font-semibold underline">
              Back to dashboard
            </Link>
          }>
            {success}
          </Alert>
        ) : null}
        {problem ? <Alert kind="error">{problem}</Alert> : null}
        {limit ? (
          <Alert
            kind="warning"
            title="Free monthly limit reached"
            action={
              <Link to="/dashboard?tab=plan" className={buttonClasses("accent", "sm")}>
                See Premium
              </Link>
            }
          >
            {limit.message}{" "}
            {limit.limit !== undefined
              ? `The Free plan allows ${limit.limit} saved receipts per month${limit.used !== undefined ? ` (${limit.used} used)` : ""}. `
              : ""}
            {limit.period_end ? `Your allowance resets after ${formatDate(limit.period_end)}. ` : ""}
            This receipt was not saved; it stays here as "Needs review". Premium has unlimited saved receipts.
          </Alert>
        ) : null}
        {notice && !problem ? <Alert kind="info">{notice}</Alert> : null}
        {r.is_sample ? (
          <Alert kind="info">This is illustrative sample data, not a real transaction.</Alert>
        ) : null}
        {r.processing_note ? <Alert kind="info" title="Note">{r.processing_note}</Alert> : null}
        {r.processing_status === "FAILED" ? (
          <Alert kind="error" title="We couldn't read this receipt automatically">
            {r.extraction_error ?? "Extraction failed."} You can fill in the details yourself
            {r.has_original_file ? ", or run the extraction again" : ""}.
          </Alert>
        ) : null}
        {warnings.map((w, i) => (
          <Alert key={`${w.code}-${i}`} kind={w.severity === "warning" ? "warning" : "info"}>
            {w.field ? <strong className="capitalize">{w.field.replace(/_/g, " ")}: </strong> : null}
            {w.message}
          </Alert>
        ))}
        {warnings.length > 0 ? (
          <p className="text-xs text-slate-600">
            These checks ask you to double-check the receipt. They don't stop you from saving.
          </p>
        ) : null}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-4">
          {editing ? (
            <ReceiptForm
              key={r.updated_at}
              receipt={r}
              config={config}
              serverErrors={fieldErrors}
              serverMessage={formMessage}
              busy={busy === "save"}
              onCancel={() => {
                setEditing(false);
                setFieldErrors({});
                setFormMessage(null);
              }}
              onSubmit={(patch, confirmAfter) => void saveFlow(patch, confirmAfter && canConfirm)}
            />
          ) : (
            <>
              <ReceiptSummary receipt={r} config={config} />
              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                {canConfirm ? (
                  <Button size="lg" onClick={() => void saveFlow(null, true)} disabled={working}>
                    {busy === "save" ? <Spinner label="Saving…" /> : (<><PiCheckCircle className="h-5 w-5" aria-hidden="true" /> Confirm and save</>)}
                  </Button>
                ) : null}
                <Button variant={canConfirm ? "secondary" : "primary"} onClick={() => { clearFeedback(); setEditing(true); }} disabled={working}>
                  <PiPencilSimple aria-hidden="true" /> Edit details
                </Button>
              </div>
              {canConfirm ? (
                <p className="text-xs text-slate-600">
                  Saving confirms the details above and counts toward your monthly allowance. Please check
                  them against the original first.
                </p>
              ) : null}
            </>
          )}

          <Card className="p-4">
            <h2 className="font-semibold text-ink">Files and actions</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {r.has_original_file ? (
                <Button variant="secondary" size="sm" disabled={working} onClick={() => void download(receiptFileUrl(r.id), r.original_filename ?? `${r.id}-original`)}>
                  <PiDownloadSimple aria-hidden="true" /> Download original
                </Button>
              ) : null}
              <Button variant="secondary" size="sm" disabled={working} onClick={() => void download(receiptPdfUrl(r.id), `${r.id}.pdf`)}>
                <PiFilePdf aria-hidden="true" /> Download PDF summary
              </Button>
              {r.has_original_file && canConfirm ? (
                <Button variant="secondary" size="sm" disabled={working} onClick={() => setConfirm("reprocess")}>
                  {busy === "reprocess" ? <Spinner label="Reading again…" /> : (<><PiArrowCounterClockwise aria-hidden="true" /> Re-run extraction</>)}
                </Button>
              ) : null}
              {archived ? (
                <Button variant="secondary" size="sm" disabled={working} onClick={() => void simple("archive", () => unarchiveReceipt(id), "Receipt restored.")}>
                  <PiArchive aria-hidden="true" /> Unarchive
                </Button>
              ) : (
                <Button variant="secondary" size="sm" disabled={working} onClick={() => void simple("archive", () => archiveReceipt(id), "Receipt archived. It's hidden from your main list but not deleted.")}>
                  <PiArchive aria-hidden="true" /> Archive
                </Button>
              )}
              <Button variant="danger" size="sm" disabled={working} onClick={() => setConfirm("delete")}>
                <PiTrash aria-hidden="true" /> Delete
              </Button>
            </div>
            <p className="mt-3 text-xs text-slate-600">
              TradeTrack gives suggestions, not tax, accounting or legal advice. Category and tax details
              may be wrong, and whether an expense is deductible or tax is recoverable is for you and your
              accountant to decide.
            </p>
          </Card>
        </div>

        <aside aria-label="Original receipt" className="space-y-2 lg:sticky lg:top-20 lg:self-start">
          <h2 className="font-semibold text-ink">Original file</h2>
          {r.original_filename ? <p className="break-all text-xs text-slate-600">{r.original_filename}</p> : null}
          <FilePreview receipt={r} />
        </aside>
      </div>

      {confirm === "delete" ? (
        <ConfirmDialog
          title="Delete this receipt?"
          confirmLabel="Delete permanently"
          danger
          busy={busy === "delete"}
          onCancel={() => setConfirm(null)}
          onConfirm={() => void doDelete()}
        >
          This permanently removes the receipt and its original file. It can't be undone. If you only want
          it out of your list, archive it instead.
        </ConfirmDialog>
      ) : null}
      {confirm === "reprocess" ? (
        <ConfirmDialog
          title="Run extraction again?"
          confirmLabel="Re-run extraction"
          onCancel={() => setConfirm(null)}
          onConfirm={() => void doReprocess()}
        >
          TradeTrack will read the stored file again. The fields will be replaced with the new results, so
          any edits you've made to this receipt may be lost.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
