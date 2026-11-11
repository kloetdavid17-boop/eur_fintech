// Landing page of the emailed password-reset link: /reset-password?token=...
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { apiErrorInfo, resetPassword } from "../api";
import { useAuth } from "../auth";
import { Alert } from "../components/Alert";
import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input } from "../components/Input";
import { Spinner } from "../components/Spinner";

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const { openAuthModal, setNotice } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) return setError("Your password needs at least 8 characters.");
    if (password !== confirm) return setError("The two passwords don't match.");
    setBusy(true);
    try {
      await resetPassword(token, password);
      setNotice({ kind: "success", text: "Your password was changed. Sign in with your new password." });
      navigate("/", { replace: true });
      openAuthModal("login");
    } catch (err) {
      const info = apiErrorInfo(err);
      setError(info.status === 429 ? "Too many attempts. Please wait a few minutes and try again." : info.message);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md px-4 py-12">
      <Card className="p-6">
        <h1 className="text-xl font-bold text-slate-900">Choose a new password</h1>
        {!token ? (
          <div className="mt-4 space-y-4">
            <Alert kind="error">This reset link is incomplete. Please use the link from your email, or request a new one.</Alert>
            <Button className="w-full" onClick={() => { navigate("/"); openAuthModal("login"); }}>
              Go to sign in
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-4 space-y-4">
            <Input label="New password" type="password" autoComplete="new-password" required minLength={8}
              hint="At least 8 characters." value={password} onChange={(e) => setPassword(e.target.value)} />
            <Input label="Confirm new password" type="password" autoComplete="new-password" required minLength={8}
              value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            <div aria-live="polite">{error ? <Alert kind="error">{error}</Alert> : null}</div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? <Spinner label="Saving…" /> : "Change password"}
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}
