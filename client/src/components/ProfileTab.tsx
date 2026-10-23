// Profile, business settings and privacy (data export, account deletion).
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { PiDownloadSimple } from "react-icons/pi";
import { accountExportUrl, apiErrorInfo, deleteAccount, updateMe, type ProfilePatch } from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { downloadFile } from "../lib/download";
import { isEmail } from "../lib/format";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { Card } from "./Card";
import { Input, Select } from "./Input";
import { Modal } from "./Modal";
import { PageSpinner, Spinner } from "./Spinner";

export function ProfileTab() {
  const { user, setUser, logout } = useAuth();
  const { data: config } = useConfig();
  const navigate = useNavigate();

  const [form, setForm] = useState(() => ({
    first_name: user?.first_name ?? "",
    last_name: user?.last_name ?? "",
    business_name: user?.business_name ?? "",
    province: user?.province ?? "ON",
    accountant_email: user?.accountant_email ?? "",
    registered: user?.gst_hst_registered === true ? "yes" : user?.gst_hst_registered === false ? "no" : "unknown",
    gst_hst_number: user?.gst_hst_number ?? "",
  }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (!user) return <PageSpinner />;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    const found: Record<string, string> = {};
    if (!form.first_name.trim()) found.first_name = "Enter your first name.";
    if (!form.last_name.trim()) found.last_name = "Enter your last name.";
    if (form.accountant_email.trim() && !isEmail(form.accountant_email.trim())) found.accountant_email = "Enter a valid email address.";
    setErrors(found);
    if (Object.keys(found).length) return;
    const body: ProfilePatch = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      business_name: form.business_name.trim() || null,
      province: form.province,
      accountant_email: form.accountant_email.trim() || null,
      gst_hst_registered: form.registered === "yes" ? true : form.registered === "no" ? false : null,
      gst_hst_number: form.registered === "yes" ? form.gst_hst_number.trim() || null : null,
    };
    setSaving(true);
    try {
      setUser(await updateMe(body));
      setMsg({ kind: "success", text: "Your settings were saved." });
    } catch (err) {
      setMsg({ kind: "error", text: apiErrorInfo(err).message });
    } finally {
      setSaving(false);
    }
  }

  async function exportData() {
    setExporting(true);
    setMsg(null);
    try {
      await downloadFile(accountExportUrl(), "tradetrack-my-data.json");
    } catch (err) {
      setMsg({ kind: "error", text: err instanceof Error ? err.message : "The download failed." });
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card className="p-4">
        <h2 className="text-lg font-bold text-ink">Profile and business</h2>
        <form onSubmit={save} className="mt-3 space-y-4" noValidate>
          {msg ? <Alert kind={msg.kind}>{msg.text}</Alert> : null}
          <p className="text-sm text-slate-700">Signed in as <strong className="break-all">{user.email}</strong></p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="First name" value={form.first_name} onChange={set("first_name")} error={errors.first_name} autoComplete="given-name" />
            <Input label="Last name" value={form.last_name} onChange={set("last_name")} error={errors.last_name} autoComplete="family-name" />
            <Input label="Business name (optional)" value={form.business_name} onChange={set("business_name")} autoComplete="organization" />
            <Select label="Home province or territory" value={form.province} onChange={set("province")}>
              {(config?.provinces ?? [{ code: form.province, name: form.province, tax_hint: "" }]).map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
          <Input
            label="Accountant's email (optional)"
            type="email"
            hint="Used only when you choose to email a monthly summary."
            value={form.accountant_email}
            onChange={set("accountant_email")}
            error={errors.accountant_email}
          />
          <fieldset className="space-y-3 rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-sm font-semibold text-ink">GST/HST registration</legend>
            <Select
              label="Is your business registered for GST/HST?"
              hint="TradeTrack doesn't assume either way. This is just recorded for your reference."
              value={form.registered}
              onChange={set("registered")}
            >
              <option value="unknown">Not specified</option>
              <option value="yes">Yes, registered</option>
              <option value="no">No, not registered</option>
            </Select>
            {form.registered === "yes" ? (
              <Input label="GST/HST number" value={form.gst_hst_number} onChange={set("gst_hst_number")} autoComplete="off" />
            ) : null}
          </fieldset>
          <Button type="submit" disabled={saving}>
            {saving ? <Spinner label="Saving…" /> : "Save settings"}
          </Button>
        </form>
      </Card>

      <Card className="space-y-3 p-4">
        <h2 className="text-lg font-bold text-ink">Privacy</h2>
        <p className="text-sm text-slate-700">
          Your receipts and files are private to your account: they are only available when you are
          signed in, and no one else can open them by link. TradeTrack doesn't store payment card
          details.
        </p>
        <div>
          <Button variant="secondary" disabled={exporting} onClick={() => void exportData()}>
            {exporting ? <Spinner label="Preparing…" /> : (<><PiDownloadSimple aria-hidden="true" /> Download my data</>)}
          </Button>
          <p className="mt-1 text-xs text-slate-600">A JSON file with your account details and all of your receipts.</p>
        </div>
        <div className="border-t border-slate-200 pt-3">
          <h3 className="font-semibold text-ink">Delete my account</h3>
          <p className="mt-1 text-sm text-slate-700">
            Permanently deletes your account, all receipts and stored files. This can't be undone.
          </p>
          <Button variant="danger" className="mt-2" onClick={() => setDeleting(true)}>
            Delete my account
          </Button>
        </div>
      </Card>

      {deleting ? (
        <DeleteAccountModal
          onClose={() => setDeleting(false)}
          onDeleted={async () => {
            try {
              await logout();
            } catch {
              /* already signed out */
            }
            navigate("/", { replace: true });
          }}
        />
      ) : null}
    </div>
  );
}

function DeleteAccountModal({ onClose, onDeleted }: { onClose: () => void; onDeleted: () => Promise<void> }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password) {
      setError("Enter your password to confirm.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      await onDeleted();
    } catch (err) {
      const info = apiErrorInfo(err);
      setError(info.status === 401 || info.status === 403 ? "That password isn't correct." : info.message);
      setBusy(false);
    }
  }

  return (
    <Modal title="Delete your account?" onClose={busy ? () => undefined : onClose} size="sm">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-slate-700">
          All of your receipts and files will be permanently deleted. Enter your password to confirm.
        </p>
        <Input label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <div aria-live="polite">{error ? <Alert kind="error">{error}</Alert> : null}</div>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant="danger" disabled={busy}>
            {busy ? <Spinner label="Deleting…" /> : "Delete everything"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
