import { useId, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const FIELD =
  "w-full rounded-lg border bg-white px-3 py-2.5 text-base text-slate-900 placeholder:text-slate-500 sm:text-sm disabled:bg-slate-100";

function Wrapper({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-800">
        {label}
      </label>
      {children}
      {hint && !error ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-600">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-err`} className="mt-1 text-xs font-medium text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const describe = (id: string, hint?: string, error?: string | null) =>
  error ? `${id}-err` : hint ? `${id}-hint` : undefined;
const border = (error?: string | null) => (error ? "border-red-600" : "border-slate-300");

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string | null;
}

export function Input({ label, hint, error, id, className = "", ...rest }: InputProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Wrapper id={fid} label={label} hint={hint} error={error}>
      <input
        id={fid}
        aria-invalid={error ? true : undefined}
        aria-describedby={describe(fid, hint, error)}
        className={`${FIELD} ${border(error)} ${className}`}
        {...rest}
      />
    </Wrapper>
  );
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  hint?: string;
  error?: string | null;
}

export function Select({ label, hint, error, id, className = "", children, ...rest }: SelectProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Wrapper id={fid} label={label} hint={hint} error={error}>
      <select
        id={fid}
        aria-invalid={error ? true : undefined}
        aria-describedby={describe(fid, hint, error)}
        className={`${FIELD} ${border(error)} ${className}`}
        {...rest}
      >
        {children}
      </select>
    </Wrapper>
  );
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: string;
  error?: string | null;
}

export function Textarea({ label, hint, error, id, className = "", ...rest }: TextareaProps) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Wrapper id={fid} label={label} hint={hint} error={error}>
      <textarea
        id={fid}
        aria-invalid={error ? true : undefined}
        aria-describedby={describe(fid, hint, error)}
        className={`${FIELD} ${border(error)} ${className}`}
        {...rest}
      />
    </Wrapper>
  );
}
