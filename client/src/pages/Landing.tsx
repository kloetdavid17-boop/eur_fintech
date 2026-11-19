// Page 1: landing + receipt capture. The upload area is the first thing under the headline.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { PiCamera, PiEnvelopeSimple, PiListChecks, PiUserPlus } from "react-icons/pi";
import { apiErrorInfo, processReceipt } from "../api";
import { useAuth } from "../auth";
import { Alert } from "../components/Alert";
import { Button, buttonClasses } from "../components/Button";
import { Card } from "../components/Card";
import { limitLabel, priceLabel } from "../components/PlanCards";
import { SampleReceiptDemo } from "../components/SampleReceiptDemo";
import { Spinner } from "../components/Spinner";
import { UploadZone } from "../components/UploadZone";
import { useConfig } from "../hooks/useConfig";
import { formatBytes } from "../lib/format";

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
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [pending, setPending] = useState<File | null>(null);
  const [busyFile, setBusyFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  async function run(file: File) {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    setBusyFile(file);
    try {
      const receipt = await processReceipt(file);
      void queryClient.invalidateQueries({ queryKey: ["receipts"] });
      navigate(`/receipts/${receipt.id}`);
    } catch (err) {
      const info = apiErrorInfo(err, "We couldn't process that file. Please try again.");
      const receiptId = typeof info.data.receipt_id === "string" ? info.data.receipt_id : null;
      if (receiptId && (info.code === "extraction_failed" || info.code === "ai_not_configured")) {
        // The file was kept: send the user to the receipt so they can fill it in by hand.
        navigate(`/receipts/${receiptId}`, { state: { notice: info.message } });
        return;
      }
      setError(
        info.code === "ai_not_configured"
          ? `${info.message} Receipt reading isn't set up on this server yet, so this file was not processed.`
          : info.message
      );
    } finally {
      inFlight.current = false;
      setBusyFile(null);
    }
  }

  function onFile(file: File) {
    setError(null);
    if (!user) {
      // Keep the file in memory while the visitor signs in; it is not uploaded yet.
      setPending(file);
      openAuthModal("register", {
        reason: "Create a free account or sign in to process your receipt. Your file stays on this device until you do.",
        onSuccess: () => {}, // the effect below continues the upload; do not redirect to the dashboard
      });
      return;
    }
    void run(file);
  }

  // Once the visitor is signed in (via the modal or the header), continue the upload.
  useEffect(() => {
    if (user && pending && !inFlight.current) {
      const file = pending;
      setPending(null);
      void run(file);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, pending]);

  const busy = busyFile !== null;
  const freePlan = config?.plans.find((p) => p.id === "FREE");
  const premiumPlan = config?.plans.find((p) => p.id === "PREMIUM");

  const uploadBlock = (
    <div id="upload" className="scroll-mt-20">
      {busy ? (
        <Card className="p-8 text-center">
          <div aria-live="polite" className="space-y-2">
            <Spinner className="mx-auto h-8 w-8 text-brand" />
            <p className="text-base font-semibold text-ink">Reading your receipt…</p>
            <p className="text-sm text-slate-600">
              {busyFile?.name} ({formatBytes(busyFile?.size ?? 0)}). This can take up to a minute.
              Please keep this page open.
            </p>
          </div>
        </Card>
      ) : (
        <UploadZone upload={config?.upload} busy={busy} onFile={onFile} />
      )}
      {pending && !user && !loading ? (
        <Alert
          kind="info"
          className="mt-3"
          title={`Ready: ${pending.name} (${formatBytes(pending.size)})`}
          action={
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => openAuthModal("register", { onSuccess: () => {} })}>
                Create free account
              </Button>
              <Button size="sm" variant="secondary" onClick={() => openAuthModal("login", { onSuccess: () => {} })}>
                Sign in
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
                Remove file
              </Button>
            </div>
          }
        >
          Sign in or create an account to process it. Nothing has been uploaded yet.
        </Alert>
      ) : null}
      {error ? (
        <Alert kind="error" className="mt-3" title="That didn't work">
          {error}
        </Alert>
      ) : null}
      {!user && !loading && !pending ? (
        <p className="mt-2 text-sm text-slate-600">
          Choosing a file asks you to create a free account first, so your receipts stay private to you.
        </p>
      ) : null}
    </div>
  );

  return (
    <div className="space-y-12">
      <section aria-labelledby="hero-title" className="space-y-4">
        <div className="max-w-2xl">
          <h1 id="hero-title" className="text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">
            Less paperwork. More business.
          </h1>
          <p className="mt-2 text-base text-slate-700 sm:text-lg">
            TradeTrack reads your receipts for you. Upload a photo or PDF and it pulls out the merchant, date and
            GST/HST/PST/QST, suggests an expense category, and files it in your private account. Built for Canadian
            tradespeople, contractors and small businesses.
          </p>
          <p className="mt-3 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-brand-soft px-3 py-1.5 text-sm font-semibold text-brand">
            {freePlan && premiumPlan ? (
              <>
                <span>Free: {limitLabel(freePlan).toLowerCase()}.</span>
                <span>Premium: {priceLabel(premiumPlan)}, unlimited.</span>
                <Link to="/pricing" className="underline">Compare plans</Link>
              </>
            ) : (
              <>
                <span>Free to start, no credit card.</span>
                <Link to="/pricing" className="underline">See pricing</Link>
              </>
            )}
          </p>
        </div>

        {!config && !configError && failureCount > 0 ? (
          <Alert kind="info" title="The server is waking up">
            TradeTrack runs on a free hosting plan that sleeps when idle. This can take up to a minute the first
            time; the page will update by itself.
          </Alert>
        ) : null}
        {configError ? (
          <Alert kind="warning" title="Couldn't load settings from the server">
            You can still try uploading. If something fails, refresh the page in a moment.
          </Alert>
        ) : null}
        {config && !config.services.ai_configured ? (
          <Alert kind="warning" title="Receipt reading is not set up on this server yet">
            Uploads are accepted but no AI extraction will run, so you would need to type the receipt
            details in yourself.
          </Alert>
        ) : null}

        {user ? (
          <>
            {uploadBlock}
            <Link to="/dashboard" className={buttonClasses("secondary")}>
              Go to my dashboard
            </Link>
          </>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button size="lg" onClick={() => openAuthModal("register")}>
              Create free account
            </Button>
            <a href="#sample" className={buttonClasses("secondary", "lg")}>
              See a sample receipt
            </a>
            <Button size="lg" variant="ghost" onClick={() => openAuthModal("login")}>
              Sign in
            </Button>
          </div>
        )}
      </section>

      <section id="sample" aria-labelledby="demo-title" className="scroll-mt-20 space-y-3">
        <h2 id="demo-title" className="text-xl font-bold text-ink">
          Try it: see how a receipt is read (no sign-up needed)
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

      {!user ? (
        <section aria-labelledby="own-title" className="space-y-3">
          <h2 id="own-title" className="text-xl font-bold text-ink">
            Ready to try your own receipt?
          </h2>
          {uploadBlock}
        </section>
      ) : null}

      {config?.services.inbound_email_configured ? (
        <section aria-labelledby="email-title">
          <Card className="p-5">
            <div className="flex items-start gap-3">
              <PiEnvelopeSimple className="mt-1 h-7 w-7 shrink-0 text-brand" aria-hidden="true" />
              <div className="min-w-0 space-y-2">
                <h2 id="email-title" className="text-xl font-bold text-ink">
                  Forward emailed receipts <span className="text-sm font-semibold text-slate-600">(Premium)</span>
                </h2>
                <p className="text-sm text-slate-700">
                  Premium accounts get a private forwarding address. Forward a receipt or invoice email from a
                  supplier and TradeTrack processes the PDF or image attachments the same way as an upload. The
                  result lands in your dashboard marked <strong>Needs review</strong>, so you always confirm it
                  before it is saved.
                </p>
              </div>
            </div>
          </Card>
        </section>
      ) : null}

      <section aria-labelledby="plans-title" className="space-y-3">
        <h2 id="plans-title" className="text-xl font-bold text-ink">
          Free or Premium
        </h2>
        {freePlan && premiumPlan ? (
          <div className="grid gap-3 md:grid-cols-2">
            {[freePlan, premiumPlan].map((plan) => (
              <Card key={plan.id} className={`p-4 ${plan.id === "PREMIUM" ? "border-2 border-brand" : ""}`}>
                <p className="font-bold text-ink">{plan.name}</p>
                <p className="text-2xl font-extrabold text-ink">{priceLabel(plan)}</p>
                <p className="text-sm text-slate-700">{limitLabel(plan)}</p>
                {plan.id === "PREMIUM" ? (
                  <p className="mt-1 text-sm text-slate-700">Plus summaries, exports and the accountant package.</p>
                ) : (
                  <p className="mt-1 text-sm text-slate-700">Upload, AI reading, review and search.</p>
                )}
              </Card>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-600">
            Free to start. <Link to="/pricing" className="font-semibold text-brand underline">See the plans</Link>
          </p>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          <Link to="/pricing" className={buttonClasses("primary")}>
            Compare plans and upgrade
          </Link>
          {!user ? (
            <Button variant="secondary" onClick={() => openAuthModal("register")}>
              Create free account
            </Button>
          ) : null}
        </div>
      </section>
    </div>
  );
}
