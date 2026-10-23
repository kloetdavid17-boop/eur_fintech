export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="TradeTrack logo">
      <rect width="32" height="32" rx="7" fill="#1d4ed8" />
      <path d="M8 5.5h14v19l-2.33-1.67L17.33 24.5 15 22.83 12.67 24.5l-2.34-1.67L8 24.5z" fill="#fff" />
      <rect x="11" y="9.5" width="8" height="1.7" rx=".85" fill="#93c5fd" />
      <rect x="11" y="13.2" width="8" height="1.7" rx=".85" fill="#93c5fd" />
      <rect x="11" y="16.9" width="5" height="1.7" rx=".85" fill="#93c5fd" />
      <circle cx="23" cy="23" r="6" fill="#f59e0b" stroke="#1d4ed8" strokeWidth="1.5" />
      <path
        d="M20.2 23.2l1.9 1.9 3.4-3.8"
        fill="none"
        stroke="#0f172a"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <LogoMark className="h-8 w-8 shrink-0" />
      <span className="text-xl font-extrabold tracking-tight text-ink">
        Trade<span className="text-brand">Track</span>
      </span>
    </span>
  );
}
