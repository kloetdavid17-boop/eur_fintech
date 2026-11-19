// Receipt upload for signed-in users: drop zone, progress, and hand-off to the receipt page.
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiErrorInfo, processReceipt } from "../api";
import { useConfig } from "../hooks/useConfig";
import { formatBytes } from "../lib/format";
import { Alert } from "./Alert";
import { Card } from "./Card";
import { Spinner } from "./Spinner";
import { UploadZone } from "./UploadZone";

export function UploadPanel() {
  const { data: config } = useConfig();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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

  return (
    <section id="upload" aria-label="Add a receipt" className="scroll-mt-20 space-y-3">
      {config && !config.services.ai_configured ? (
        <Alert kind="warning" title="Receipt reading is not set up on this server yet">
          Uploads are accepted but no AI extraction will run, so you would need to type the receipt details in yourself.
        </Alert>
      ) : null}
      {busyFile ? (
        <Card className="p-8 text-center">
          <div aria-live="polite" className="space-y-2">
            <Spinner className="mx-auto h-8 w-8 text-brand" />
            <p className="text-base font-semibold text-ink">Reading your receipt…</p>
            <p className="text-sm text-slate-600">
              {busyFile.name} ({formatBytes(busyFile.size)}). This can take up to a minute. Please keep this page open.
            </p>
          </div>
        </Card>
      ) : (
        <UploadZone upload={config?.upload} busy={false} onFile={(f) => void run(f)} />
      )}
      {error ? (
        <Alert kind="error" title="That didn't work">
          {error}
        </Alert>
      ) : null}
    </section>
  );
}
