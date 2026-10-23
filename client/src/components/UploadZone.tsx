// Receipt capture: drag-and-drop area, file picker, and a separate "Take photo" button
// (opens the camera on phones via capture="environment"; on desktop it simply opens
// the file picker). File type and size are validated here against /api/config, but
// the server validates again — this only gives faster, friendlier feedback.
import { useRef, useState, type DragEvent } from "react";
import { PiCamera, PiFileArrowUp, PiUploadSimple } from "react-icons/pi";
import type { AppConfig } from "../api";
import { formatBytes } from "../lib/format";
import { Alert } from "./Alert";
import { Button } from "./Button";

const TYPE_LABELS: Record<string, string> = {
  "image/jpeg": "JPEG",
  "image/png": "PNG",
  "image/webp": "WebP",
  "application/pdf": "PDF",
};

export function validateFile(file: File, upload: AppConfig["upload"] | undefined): string | null {
  if (file.size === 0) return "That file is empty. Please choose a different one.";
  if (!upload) return null; // config not loaded: let the server decide
  if (!upload.allowed_types.includes(file.type)) {
    const names = upload.allowed_types.map((t) => TYPE_LABELS[t] ?? t).join(", ");
    return `"${file.name}" isn't a supported file type. Please upload one of: ${names}.`;
  }
  const maxBytes = upload.max_mb * 1024 * 1024;
  if (file.size > maxBytes) {
    return `"${file.name}" is ${formatBytes(file.size)}, which is over the ${upload.max_mb} MB limit. Try a smaller photo or PDF.`;
  }
  return null;
}

export function UploadZone({
  upload,
  busy,
  onFile,
}: {
  upload: AppConfig["upload"] | undefined;
  busy: boolean;
  onFile: (file: File) => void;
}) {
  const pickRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = upload ? [...upload.allowed_types, ".pdf"].join(",") : "image/*,application/pdf";

  function handle(file: File | undefined) {
    if (!file) return;
    const problem = validateFile(file, upload);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    onFile(file);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (busy) return;
    handle(e.dataTransfer.files?.[0]);
  }

  const typesText = upload
    ? upload.allowed_types.map((t) => TYPE_LABELS[t] ?? t).join(", ")
    : "JPEG, PNG, WebP or PDF";

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-2xl border-2 border-dashed p-5 text-center transition-colors sm:p-8 ${
          dragging ? "border-brand bg-brand-soft" : "border-slate-300 bg-white"
        }`}
      >
        <PiFileArrowUp className="mx-auto h-10 w-10 text-brand" aria-hidden="true" />
        <p className="mt-2 text-base font-semibold text-ink">Drop a receipt here</p>
        <p className="text-sm text-slate-600">
          or choose a file from your device. {typesText}
          {upload ? `, up to ${upload.max_mb} MB.` : "."}
        </p>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-center">
          <Button size="lg" disabled={busy} onClick={() => pickRef.current?.click()}>
            <PiUploadSimple className="h-5 w-5" aria-hidden="true" /> Choose file
          </Button>
          <Button
            size="lg"
            variant="secondary"
            disabled={busy}
            onClick={() => cameraRef.current?.click()}
          >
            <PiCamera className="h-5 w-5" aria-hidden="true" /> Take photo
          </Button>
        </div>

        {/* Visually hidden inputs; the buttons above trigger them. */}
        <input
          ref={pickRef}
          type="file"
          accept={accept}
          className="sr-only"
          tabIndex={-1}
          aria-label="Choose a receipt file"
          onChange={(e) => {
            handle(e.target.files?.[0]);
            e.target.value = ""; // allow re-selecting the same file
          }}
        />
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          tabIndex={-1}
          aria-label="Take a photo of a receipt"
          onChange={(e) => {
            handle(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>

      <div aria-live="assertive">
        {error ? (
          <Alert kind="error" className="mt-3">
            {error}
          </Alert>
        ) : null}
      </div>
    </div>
  );
}
