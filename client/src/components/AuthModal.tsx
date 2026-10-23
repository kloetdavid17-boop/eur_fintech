// Sign-in / create-account modal. Opened from anywhere via useAuth().openAuthModal().
import { useState, type FormEvent } from "react";
import { apiErrorInfo } from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { Input, Select } from "./Input";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

export function AuthModal() {
  const { modal, closeAuthModal, setAuthMode } = useAuth();
  if (!modal.open) return null;
  // Re-mount the form when the mode flips so fields and errors reset cleanly.
  return (
    <Modal
      title={modal.mode === "login" ? "Sign in to TradeTrack" : "Create your free account"}
      onClose={closeAuthModal}
    >
      {modal.reason ? (
        <Alert kind="info" className="mb-4">
          {modal.reason}
        </Alert>
      ) : null}
      {modal.mode === "login" ? (
        <LoginForm key="login" onSwitch={() => setAuthMode("register")} />
      ) : (
        <RegisterForm key="register" onSwitch={() => setAuthMode("login")} />
      )}
    </Modal>
  );
}

function useFinish() {
  const { modal, closeAuthModal } = useAuth();
  return (user: Parameters<NonNullable<typeof modal.onSuccess>>[0]) => {
    const cb = modal.onSuccess;
    closeAuthModal();
    cb?.(user);
  };
}

function LoginForm({ onSwitch }: { onSwitch: () => void }) {
  const { login } = useAuth();
  const finish = useFinish();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      finish(await login(email.trim(), password));
    } catch (err) {
      const info = apiErrorInfo(err);
      setError(
        info.status === 429
          ? "Too many sign-in attempts. Please wait a few minutes and try again."
          : info.status === 401
            ? "That email and password don't match. Please try again."
            : info.message
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate={false}>
      <Input
        label="Email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Input
        label="Password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <div aria-live="polite">{error ? <Alert kind="error">{error}</Alert> : null}</div>
      <Button type="submit" className="w-full" disabled={busy}>
        {busy ? <Spinner label="Signing in…" /> : "Sign in"}
      </Button>
      <p className="text-center text-sm text-slate-700">
        New to TradeTrack?{" "}
        <button type="button" className="font-semibold text-brand underline" onClick={onSwitch}>
          Create a free account
        </button>
      </p>
    </form>
  );
}

function RegisterForm({ onSwitch }: { onSwitch: () => void }) {
  const { register } = useAuth();
  const { data: config } = useConfig();
  const finish = useFinish();
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
    business_name: "",
    province: "ON",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (form.password.length < 8) {
      setError("Your password needs at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      finish(
        await register({
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          email: form.email.trim(),
          password: form.password,
          business_name: form.business_name.trim() || undefined,
          province: form.province,
        })
      );
    } catch (err) {
      const info = apiErrorInfo(err);
      setError(
        info.status === 409 ? "An account with this email already exists. Try signing in." : info.message
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Input
          label="First name"
          autoComplete="given-name"
          required
          value={form.first_name}
          onChange={set("first_name")}
        />
        <Input
          label="Last name"
          autoComplete="family-name"
          required
          value={form.last_name}
          onChange={set("last_name")}
        />
      </div>
      <Input
        label="Email"
        type="email"
        autoComplete="email"
        required
        value={form.email}
        onChange={set("email")}
      />
      <Input
        label="Password"
        type="password"
        autoComplete="new-password"
        required
        minLength={8}
        hint="At least 8 characters."
        value={form.password}
        onChange={set("password")}
      />
      <Input
        label="Business name (optional)"
        autoComplete="organization"
        value={form.business_name}
        onChange={set("business_name")}
      />
      {config?.provinces?.length ? (
        <Select
          label="Province or territory"
          hint="Used for tax hints only. You can change it per receipt."
          value={form.province}
          onChange={set("province")}
        >
          {config.provinces.map((p) => (
            <option key={p.code} value={p.code}>
              {p.name}
            </option>
          ))}
        </Select>
      ) : null}
      <div aria-live="polite">{error ? <Alert kind="error">{error}</Alert> : null}</div>
      <Button type="submit" className="w-full" disabled={busy}>
        {busy ? <Spinner label="Creating account…" /> : "Create free account"}
      </Button>
      <p className="text-xs text-slate-600">
        TradeTrack provides suggestions only and is not tax or accounting advice.
      </p>
      <p className="text-center text-sm text-slate-700">
        Already have an account?{" "}
        <button type="button" className="font-semibold text-brand underline" onClick={onSwitch}>
          Sign in
        </button>
      </p>
    </form>
  );
}
