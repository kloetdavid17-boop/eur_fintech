// Home: the pitch for a visitor who is not signed in. One job: show what TradeTrack does and get them to
// create a free account. Signed-in users go straight to their dashboard, where uploading happens.
// The original one-page version is kept at /classic for comparison.
import { Link, Navigate } from "react-router-dom";
import { PiCamera, PiListChecks, PiUserPlus } from "react-icons/pi";
import { useAuth } from "../auth";
import { Alert } from "../components/Alert";
import { Button, buttonClasses } from "../components/Button";
import { Card } from "../components/Card";
import { limitLabel, priceLabel } from "../components/PlanCards";
import { SampleReceiptDemo } from "../components/SampleReceiptDemo";
import { useConfig } from "../hooks/useConfig";

const STEPS = [
  {
    icon: PiUserPlus,
    title: "1. Create a free account",
    text: "It takes a minute and needs no credit card. Your receipts stay private to you.",
  },
  {
    icon: PiCamera,
    title: "2. Upload a receipt",
    text: "Snap a photo or upload a PDF. AI reads the merchant, date, items, GST/HST/PST/QST and total, and suggests a category.",
  },
  {
    icon: PiListChecks,
    title: "3. Check and save",
    text: "Fix anything that looks off, then save. Your records stay ready for your bookkeeping and your accountant.",
  },
];

export function Landing() {
  const { user, loading, openAuthModal } = useAuth();
  const { data: config, isError: configError, failureCount } = useConfig();

  if (!loading && user) return <Navigate to="/dashboard" replace />;

  const free = config?.plans.find((p) => p.id === "FREE");
  const premium = config?.plans.find((p) => p.id === "PREMIUM");

  return (
    <div className="space-y-12">
      <section aria-labelledby="hero-title" className="space-y-4">
        <div className="max-w-2xl">
          <h1 id="hero-title" className="text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
            Less paperwork. More business.
          </h1>
          <p className="mt-2 text-base text-slate-700 sm:text-lg">
            TradeTrack reads your receipts for you: upload a photo or PDF and it pulls out the merchant, date and
            GST/HST/PST/QST, suggests an expense category, and files it in your private account. Built for Canadian
            tradespeople, contractors and small businesses.
          </p>
          <p className="mt-3 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-brand-soft px-3 py-1.5 text-sm font-semibold text-brand">
            {free && premium ? (
              <>
                <span>Free: {limitLabel(free).toLowerCase()}.</span>
                <span>Premium: {priceLabel(premium)}.</span>
                <Link to="/pricing" className="underline">
                  Compare plans
                </Link>
              </>
            ) : (
              <>
                <span>Free to start, no credit card.</span>
                <Link to="/pricing" className="underline">
                  See pricing
                </Link>
              </>
            )}
          </p>
        </div>

        {!config && !configError && failureCount > 0 ? (
          <Alert kind="info" title="The server is waking up">
            TradeTrack runs on a free hosting plan that sleeps when idle. This can take up to a minute the first time;
            the page will update by itself.
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button size="lg" onClick={() => openAuthModal("register")}>
            Create free account
          </Button>
          <a href="#sample" className={buttonClasses("secondary", "lg")}>
            See a sample receipt
          </a>
          <button
            type="button"
            className="px-2 text-sm font-semibold text-brand underline"
            onClick={() => openAuthModal("login")}
          >
            I already have an account
          </button>
        </div>
      </section>

      <section id="sample" aria-labelledby="demo-title" className="scroll-mt-20 space-y-3">
        <h2 id="demo-title" className="text-xl font-bold text-ink">
          See how a receipt is read (no sign-up needed)
        </h2>
        <SampleReceiptDemo />
      </section>

      <section id="how" aria-labelledby="how-title" className="scroll-mt-20">
        <h2 id="how-title" className="text-xl font-bold text-ink">
          How it works
        </h2>
        <ol className="mt-3 grid gap-3 md:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, text }) => (
            <li key={title}>
              <Card className="h-full p-4">
                <Icon className="h-7 w-7 text-brand" aria-hidden="true" />
                <h3 className="mt-2 font-semibold text-ink">{title}</h3>
                <p className="mt-1 text-sm text-slate-700">{text}</p>
              </Card>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="plans-title" className="space-y-3">
        <h2 id="plans-title" className="text-xl font-bold text-ink">
          Free to start, Premium when you need more
        </h2>
        {free && premium ? (
          <div className="grid gap-3 md:grid-cols-2">
            {[free, premium].map((plan) => (
              <Card key={plan.id} className={`p-4 ${plan.id === "PREMIUM" ? "border-2 border-brand" : ""}`}>
                <p className="font-bold text-ink">{plan.name}</p>
                <p className="text-2xl font-extrabold text-ink">{priceLabel(plan)}</p>
                <p className="text-sm text-slate-700">{limitLabel(plan)}</p>
                <p className="mt-1 text-sm text-slate-700">
                  {plan.id === "PREMIUM"
                    ? "Plus summaries by month, quarter or year, exports and the accountant package."
                    : "Upload, AI reading, review and search."}
                </p>
              </Card>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button size="lg" onClick={() => openAuthModal("register")}>
            Create free account
          </Button>
          <Link to="/pricing" className={buttonClasses("secondary", "lg")}>
            Compare plans
          </Link>
        </div>
      </section>
    </div>
  );
}
