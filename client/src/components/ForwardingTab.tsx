// Email-forwarding setup: the user's private address, instructions, alias rotation, and
// the inbound log. Honest about whether the inbound service is configured.
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PiCopy } from "react-icons/pi";
import { apiErrorInfo, getInboundLog, rotateForwardingAlias } from "../api";
import { useAuth } from "../auth";
import { useConfig } from "../hooks/useConfig";
import { formatDateTime } from "../lib/format";
import { Alert } from "./Alert";
import { Button } from "./Button";
import { Card } from "./Card";
import { ConfirmDialog } from "./ConfirmDialog";
import { PremiumLock } from "./PremiumLock";
import { PageSpinner } from "./Spinner";
import { InboundBadge } from "./StatusBadge";

export function ForwardingTab({ goTo }: { goTo: (t: "plan") => void }) {
  const { user, setUser } = useAuth();
  const { data: config } = useConfig();
  const premium = user?.plan === "PREMIUM";
  const configured = config?.services.inbound_email_configured ?? false;

  const [copied, setCopied] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const log = useQuery({ queryKey: ["inbound-log"], queryFn: getInboundLog, enabled: premium && configured, retry: false });

  const rotate = useMutation({
    mutationFn: rotateForwardingAlias,
    onSuccess: (u) => {
      setUser(u);
      setConfirmRotate(false);
      setMessage({ kind: "success", text: "You have a new forwarding address. The old one no longer works." });
    },
    onError: (err) => {
      setConfirmRotate(false);
      setMessage({ kind: "error", text: apiErrorInfo(err).message });
    },
  });

  if (!user || !config) return <PageSpinner />;
  const address = user.forwarding_address;

  async function copy() {
    try {
      await navigator.clipboard.writeText(address ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setMessage({ kind: "error", text: "Couldn't copy automatically. Select the address and copy it by hand." });
    }
  }

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-bold text-ink">Email forwarding</h2>
      {message ? <Alert kind={message.kind}>{message.text}</Alert> : null}

      {!premium ? (
        <PremiumLock title="Forward receipts by email" onUpgrade={() => goTo("plan")}>
          Premium accounts get a private address. Forward a supplier's receipt email and TradeTrack
          reads the attachments for you.{" "}
          {configured ? "" : "Email forwarding is also not switched on for this server yet."}
        </PremiumLock>
      ) : !configured || !address ? (
        <Alert kind="warning" title="Email forwarding is not set up on this server">
          No inbound email service is configured, so no forwarding address can be issued and forwarded
          emails would not be received. You can still upload receipts from the home page. Once the site
          owner configures an inbound email provider, your private address will appear here.
        </Alert>
      ) : (
        <Card className="space-y-3 p-4">
          <p className="text-sm font-medium text-slate-800">Your private forwarding address</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <code className="min-w-0 flex-1 break-all rounded-lg bg-slate-100 px-3 py-2.5 text-sm font-semibold text-ink" data-testid="forwarding-address">
              {address}
            </code>
            <Button variant="secondary" onClick={() => void copy()}>
              <PiCopy aria-hidden="true" /> {copied ? "Copied" : "Copy address"}
            </Button>
          </div>
          <p className="text-xs text-slate-600">
            Treat this address like a password: anyone who has it can add receipts to your account.
          </p>
          <Button variant="ghost" size="sm" onClick={() => setConfirmRotate(true)}>
            Get a new address
          </Button>
        </Card>
      )}

      <Card className="p-4">
        <h3 className="font-semibold text-ink">How to use it</h3>
        <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm text-slate-800">
          <li>Copy your private address above and save it as a contact, for example "TradeTrack receipts".</li>
          <li>Open the receipt or invoice email from the supplier and forward it to that address, keeping the PDF or image attached.</li>
          <li>TradeTrack matches the message to your account by the address it was sent to, checks the attachments (PDF or image, up to {config.upload.max_mb} MB), and reads them the same way as an upload.</li>
          <li>The receipt appears in your Receipts list as <strong>Needs review</strong>. Check the details and confirm it. It only counts toward your allowance once saved.</li>
        </ol>
        <p className="mt-3 text-sm text-slate-700">
          Emails with no usable attachment, repeats of a receipt you already have, and anything that can't
          be read show up in the log below with a reason. TradeTrack doesn't keep the email text or subject.
        </p>
      </Card>

      {premium && configured ? (
        <section aria-labelledby="log-h" className="space-y-2">
          <h3 id="log-h" className="font-semibold text-ink">Recent forwarded emails</h3>
          {log.isLoading ? (
            <PageSpinner label="Loading log…" />
          ) : log.error ? (
            <Alert kind="error">{apiErrorInfo(log.error).message}</Alert>
          ) : !log.data?.length ? (
            <Card className="p-4 text-sm text-slate-600">Nothing has been forwarded yet.</Card>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="w-full min-w-[34rem] text-left text-sm">
                <thead className="bg-slate-50 text-slate-700">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-semibold">Received</th>
                    <th scope="col" className="px-3 py-2 font-semibold">Result</th>
                    <th scope="col" className="px-3 py-2 font-semibold">Attachments</th>
                    <th scope="col" className="px-3 py-2 font-semibold">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {log.data.map((e) => (
                    <tr key={e.id}>
                      <td className="whitespace-nowrap px-3 py-2">{formatDateTime(e.received_at)}</td>
                      <td className="px-3 py-2"><InboundBadge status={e.status} /></td>
                      <td className="px-3 py-2">{e.attachments}</td>
                      <td className="px-3 py-2">
                        {e.reason ? <span className="block text-slate-700">{e.reason}</span> : null}
                        {e.receipt_ids.map((rid) => (
                          <Link key={rid} to={`/receipts/${rid}`} className="mr-2 font-semibold text-brand underline">
                            {rid}
                          </Link>
                        ))}
                        {!e.reason && e.receipt_ids.length === 0 ? <span className="text-slate-600">Not available</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {confirmRotate ? (
        <ConfirmDialog
          title="Get a new forwarding address?"
          confirmLabel="Get new address"
          busy={rotate.isPending}
          onCancel={() => setConfirmRotate(false)}
          onConfirm={() => rotate.mutate()}
        >
          Your current address will stop working straight away. Update any contacts or auto-forward rules
          that use it.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
