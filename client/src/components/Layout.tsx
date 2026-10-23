// App shell: TradeTrack header (hamburger menu on phones), routed page, footer with
// the not-tax-advice note.
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { PiList, PiX } from "react-icons/pi";
import { useAuth } from "../auth";
import { Button } from "./Button";
import { Logo } from "./Logo";

export function Layout() {
  const { user, loading, openAuthModal, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => setOpen(false), [location.pathname, location.search]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm font-semibold ${
      isActive ? "bg-brand-soft text-brand" : "text-slate-700 hover:bg-slate-100"
    }`;

  async function signOut() {
    await logout();
    navigate("/", { replace: true });
  }

  const items = (
    <>
      <NavLink to="/" end className={link}>
        Upload a receipt
      </NavLink>
      {user ? (
        <NavLink to="/dashboard" className={link}>
          Dashboard
        </NavLink>
      ) : null}
    </>
  );

  const account = loading ? null : user ? (
    <>
      <span className="truncate px-1 text-sm text-slate-700" title={user.email}>
        {user.first_name}
      </span>
      <Button variant="secondary" size="sm" onClick={signOut}>
        Sign out
      </Button>
    </>
  ) : (
    <>
      <Button variant="ghost" size="sm" onClick={() => openAuthModal("login")}>
        Sign in
      </Button>
      <Button size="sm" onClick={() => openAuthModal("register")}>
        Create account
      </Button>
    </>
  );

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-2.5">
          <Link to="/" aria-label="TradeTrack home">
            <Logo />
          </Link>
          <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
            {items}
          </nav>
          <div className="hidden items-center gap-2 md:flex">{account}</div>
          <button
            type="button"
            className="rounded-lg p-2 text-slate-800 hover:bg-slate-100 md:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="mobile-menu"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <PiX className="h-6 w-6" /> : <PiList className="h-6 w-6" />}
          </button>
        </div>
        {open ? (
          <div id="mobile-menu" className="border-t border-slate-200 px-4 pb-4 pt-2 md:hidden">
            <nav aria-label="Mobile" className="flex flex-col gap-1">
              {items}
            </nav>
            <div className="mt-3 flex items-center gap-2 border-t border-slate-100 pt-3">{account}</div>
          </div>
        ) : null}
      </header>

      <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-4 py-6 text-xs text-slate-600">
          <p className="font-semibold text-slate-800">TradeTrack. Less paperwork. More business.</p>
          <p className="mt-1">
            TradeTrack provides suggestions only. Expense categories and tax details are not tax,
            accounting or legal advice, and nothing here says an expense is deductible or that tax is
            recoverable. Please check with your accountant.
          </p>
        </div>
      </footer>
    </div>
  );
}
