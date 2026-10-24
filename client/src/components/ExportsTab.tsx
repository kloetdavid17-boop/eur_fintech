// Premium exports: CSV/JSON of saved receipts, a period summary, an accountant package, and email to the accountant.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PiDownloadSimple, PiEnvelopeSimple, PiFileZip } from "react-icons/pi";
import {
  apiErrorInfo,
  emailAccountant,
  exportUrl,
  getSummary,
  packageUrl,
  summaryDownloadUrl,
  type ExportParams,
} from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { downloadFile } from "../lib/download";
import { currentMonth, defaultPeriodChoice, periodLabel, periodParams, money, type PeriodChoice } from "../lib/format";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { Card } from "./Card";
import { Input, Select } from "./Input";
import { PremiumLock } from "./PremiumLock";
import { PageSpinner, Spinner } from "./Spinner";

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
type Scope = "all" | "month" | "range";

export function ExportsTab({ goTo }: { goTo: (t: "plan" | "account") => void }) {
  const { user } = useAuth();
  const { data: config } = useConfig();
  const [scope, setScope] = useState<Scope>("month");
  const [month, setMonth] = useState(currentMonth());
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "success" | "error" | "warning"; text: string } | null>(null);

  const [period, setPeriod] = useState<PeriodChoice>(defaultPeriodChoice());
  const params = periodParams(period);
  const premium = user?.plan === "PREMIUM";
  const summary = useQuery({
    queryKey: ["summary", params],
    queryFn: () => getSummary(params!),
    enabled: premium && params !== null,
    retry: false,
  });
  const set = (patch: Partial<PeriodChoice>) => setPeriod((p) => ({ ...p, ...patch }));

  if (!user || !config) return <PageSpinner />;

  if (!premium) {
    return (
      <div className="space-y-4">
        <h2 className="text-lg font-bold text-ink">Exports</h2>
        <PremiumLock title="Exports, expense summaries and the accountant package" onUpgrade={() => goTo("plan")}>
          Premium lets you export saved receipts, see a summary by month, quarter or year (by category, tax
          type and province), and send your accountant one ZIP with the summary, a CSV and the original files. On the Free plan you can still download each receipt's PDF summary from
          its page.
        </PremiumLock>
      </div>
    );
  }

  async function download(key: string, url: string, name: string) {
    setBusy(key);
    setMsg(null);
    try {
      await downloadFile(url, name);
    } catch (err) {
      setMsg({ kind: "error", text: err instanceof Error ? err.message : "The download failed." });
    } finally {
      setBusy(null);
    }
  }

  function exportReceipts(format: "csv" | "json") {
    const p: ExportParams = { format, category: category || undefined };
    if (scope === "month") {
      if (!MONTH_RE.test(month)) return setMsg({ kind: "error", text: "Choose a month (YYYY-MM) to export." });
      p.month = month;
    } else if (scope === "range") {
      if (!from || !to) return setMsg({ kind: "error", text: "Choose both a start and an end date." });
      if (from > to) return setMsg({ kind: "error", text: "The start date must be before the end date." });
      p.date_from = from;
      p.date_to = to;
    }
    void download(format, exportUrl(p), `tradetrack-receipts.${format}`);
  }

  async function sendToAccountant() {
    setBusy("email");
    setMsg(null);
    try {
      await emailAccountant(params!);
      setMsg({ kind: "success", text: `Sent the ${periodLabel(s?.label ?? "")} CSV and summary PDF to ${user!.accountant_email}.` });
    } catch (err) {
      const info = apiErrorInfo(err);
      if (info.code === "no_accountant_email")
        setMsg({ kind: "warning", text: "Add your accountant's email address in Profile and privacy first." });
      else if (info.code === "email_not_configured")
        setMsg({ kind: "warning", text: "Email sending isn't configured on this server, so nothing was sent. Download the files and send them yourself." });
      else setMsg({ kind: "error", text: info.message });
    } finally {
      setBusy(null);
    }
  }

  const s = summary.data;
  const sumValid = params !== null;
  const fileTag = s?.label.replace(" to ", "_to_") ?? "period";
  const smtp = config.services.smtp_configured;

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-bold text-ink">Exports</h2>
      {msg ? <Alert kind={msg.kind}>{msg.text}</Alert> : null}

      <Card className="space-y-4 p-4">
        <h3 className="font-semibold text-ink">Export saved receipts</h3>
        <p className="text-sm text-slate-700">Only saved receipts are included. Values match what is stored on each receipt.</p>
        <Select label="Which receipts" value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
          <option value="month">A single month</option>
          <option value="range">A date range</option>
          <option value="all">All saved receipts</option>
        </Select>
        {scope === "month" ? (
          <Input label="Month" type="month" placeholder="YYYY-MM" value={month} onChange={(e) => setMonth(e.target.value)} />
        ) : null}
        {scope === "range" ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            <Input label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
        ) : null}
        <Select label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {config.categories.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </Select>
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy !== null} onClick={() => exportReceipts("csv")}>
            {busy === "csv" ? <Spinner label="Preparing…" /> : (<><PiDownloadSimple aria-hidden="true" /> Download CSV</>)}
          </Button>
          <Button variant="secondary" disabled={busy !== null} onClick={() => exportReceipts("json")}>
            {busy === "json" ? <Spinner label="Preparing…" /> : (<><PiDownloadSimple aria-hidden="true" /> Download JSON</>)}
          </Button>
        </div>
      </Card>

      <Card className="space-y-4 p-4">
        <h3 className="font-semibold text-ink">Expense summary</h3>
        <p className="text-sm text-slate-700">Pick a month, quarter or year to see what your saved receipts add up to.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="Period" value={period.kind} onChange={(e) => set({ kind: e.target.value as PeriodChoice["kind"] })}>
            <option value="month">A month</option>
            <option value="quarter">A quarter</option>
            <option value="year">A year</option>
            <option value="custom">A custom date range</option>
          </Select>
          {period.kind === "month" ? (
            <Input label="Month" type="month" placeholder="YYYY-MM" value={period.month} onChange={(e) => set({ month: e.target.value })} error={sumValid ? null : "Choose a month (YYYY-MM)."} />
          ) : null}
          {period.kind === "quarter" ? (
            <div className="grid grid-cols-2 gap-3">
              <Select label="Quarter" value={period.quarter} onChange={(e) => set({ quarter: e.target.value })}>
                <option value="1">Q1 (Jan to Mar)</option>
                <option value="2">Q2 (Apr to Jun)</option>
                <option value="3">Q3 (Jul to Sep)</option>
                <option value="4">Q4 (Oct to Dec)</option>
              </Select>
              <Input label="Year" inputMode="numeric" maxLength={4} value={period.year} onChange={(e) => set({ year: e.target.value })} error={sumValid ? null : "Enter a 4-digit year."} />
            </div>
          ) : null}
          {period.kind === "year" ? (
            <Input label="Year" inputMode="numeric" maxLength={4} value={period.year} onChange={(e) => set({ year: e.target.value })} error={sumValid ? null : "Enter a 4-digit year."} />
          ) : null}
          {period.kind === "custom" ? (
            <div className="grid grid-cols-2 gap-3">
              <Input label="From" type="date" value={period.from} onChange={(e) => set({ from: e.target.value })} />
              <Input label="To" type="date" value={period.to} onChange={(e) => set({ to: e.target.value })} error={period.from && period.to && period.from > period.to ? "The start date must be before the end date." : null} />
            </div>
          ) : null}
        </div>
        {summary.isLoading && sumValid ? (
          <PageSpinner label="Loading summary…" />
        ) : summary.error ? (
          <Alert kind="error">{apiErrorInfo(summary.error).message}</Alert>
        ) : s ? (
          s.count === 0 ? (
            <p className="text-sm text-slate-600">No saved receipts for {periodLabel(s.label)}.</p>
          ) : (
            <div className="space-y-4 text-sm">
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  ["Receipts", String(s.count)],
                  ["Subtotal", money(s.subtotal, s.currency)],
                  ["Tax total", money(s.tax_total, s.currency)],
                  ["Total", money(s.total, s.currency)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-slate-50 p-3">
                    <dt className="text-xs text-slate-600">{k}</dt>
                    <dd className="text-base font-bold tabular-nums text-ink">{v}</dd>
                  </div>
                ))}
              </dl>
              {s.undated_count > 0 || s.flagged_count > 0 ? (
                <Alert kind="warning">
                  {s.undated_count > 0 ? `${s.undated_count} saved receipt${s.undated_count === 1 ? " has" : "s have"} no date and may not be counted in any period. ` : ""}
                  {s.flagged_count > 0 ? `${s.flagged_count} receipt${s.flagged_count === 1 ? " has" : "s have"} unresolved warnings worth reviewing.` : ""}
                </Alert>
              ) : null}
              <div className="overflow-x-auto">
                <table className="w-full min-w-[28rem] text-left">
                  <caption className="mb-1 text-left font-semibold text-ink">By category</caption>
                  <thead className="text-slate-700">
                    <tr>
                      <th scope="col" className="py-1.5 pr-3 font-semibold">Category</th>
                      <th scope="col" className="py-1.5 pr-3 text-right font-semibold">Count</th>
                      <th scope="col" className="py-1.5 pr-3 text-right font-semibold">Tax</th>
                      <th scope="col" className="py-1.5 text-right font-semibold">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {s.by_category.map((c) => (
                      <tr key={c.category}>
                        <th scope="row" className="py-1.5 pr-3 font-normal">{c.category}</th>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{c.count}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{money(c.tax_total, s.currency)}</td>
                        <td className="py-1.5 text-right tabular-nums">{money(c.total, s.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[32rem] text-left">
                  <caption className="mb-1 text-left font-semibold text-ink">Tax as printed on receipts, by province</caption>
                  <thead className="text-slate-700">
                    <tr>
                      <th scope="col" className="py-1.5 pr-3 font-semibold">Province</th>
                      <th scope="col" className="py-1.5 pr-3 text-right font-semibold">Receipts</th>
                      {["GST", "HST", "PST", "QST"].map((t) => (
                        <th key={t} scope="col" className="py-1.5 pr-3 text-right font-semibold">{t}</th>
                      ))}
                      <th scope="col" className="py-1.5 text-right font-semibold">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {s.by_province.map((p) => (
                      <tr key={p.province}>
                        <th scope="row" className="py-1.5 pr-3 font-normal">{p.province}</th>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{p.count}</td>
                        {["GST", "HST", "PST", "QST"].map((t) => (
                          <td key={t} className="py-1.5 pr-3 text-right tabular-nums">{money(p.tax[t] ?? "0.00", s.currency)}</td>
                        ))}
                        <td className="py-1.5 text-right tabular-nums">{money(p.total, s.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <p className="font-semibold text-ink">Tax as printed on receipts, by type</p>
                <ul className="mt-1 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-5">
                  {Object.entries(s.by_tax_type).map(([k, v]) => (
                    <li key={k} className="flex justify-between gap-2">
                      <span>{k}</span>
                      <span className="tabular-nums">{money(v, s.currency)}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-slate-600">
                  These are totals of what the receipts show. They are not a statement of what is
                  deductible or recoverable; that is for you and your accountant to decide.
                </p>
              </div>
            </div>
          )
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={!sumValid || busy !== null} onClick={() => void download("scsv", summaryDownloadUrl(params!, "csv"), `tradetrack-summary-${fileTag}.csv`)}>
            {busy === "scsv" ? <Spinner label="Preparing…" /> : (<><PiDownloadSimple aria-hidden="true" /> Summary CSV</>)}
          </Button>
          <Button variant="secondary" disabled={!sumValid || busy !== null} onClick={() => void download("spdf", summaryDownloadUrl(params!, "pdf"), `tradetrack-summary-${fileTag}.pdf`)}>
            {busy === "spdf" ? <Spinner label="Preparing…" /> : (<><PiDownloadSimple aria-hidden="true" /> Summary PDF</>)}
          </Button>
        </div>
      </Card>

      <Card className="space-y-3 p-4">
        <h3 className="font-semibold text-ink">For your accountant</h3>
        <p className="text-sm text-slate-700">
          The accountant package is one ZIP for the period above: the summary PDF, a CSV of every receipt and the
          original receipt files, so nothing has to be chased later. It works without email.
        </p>
        <Button disabled={!sumValid || busy !== null} onClick={() => void download("zip", packageUrl(params!), `tradetrack-accountant-package-${fileTag}.zip`)}>
          {busy === "zip" ? <Spinner label="Preparing…" /> : (<><PiFileZip aria-hidden="true" /> Download accountant package</>)}
        </Button>
        {user.accountant_email ? (
          <p className="text-sm text-slate-700">
            Or email the CSV and summary PDF for this period to <strong className="break-all">{user.accountant_email}</strong>.
          </p>
        ) : (
          <Alert kind="info" action={<Button size="sm" variant="secondary" onClick={() => goTo("account")}>Add accountant email</Button>}>
            You haven't added your accountant's email address yet.
          </Alert>
        )}
        {!smtp ? (
          <Alert kind="warning">
            Email sending isn't configured on this server, so TradeTrack can't email this for you. Download
            the accountant package above and send it yourself.
          </Alert>
        ) : null}
        <Button disabled={!sumValid || !user.accountant_email || !smtp || busy !== null} onClick={() => void sendToAccountant()}>
          {busy === "email" ? <Spinner label="Sending…" /> : (<><PiEnvelopeSimple aria-hidden="true" /> Email this period to accountant</>)}
        </Button>
      </Card>
    </div>
  );
}
