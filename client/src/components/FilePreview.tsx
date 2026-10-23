// Inline preview of the original upload. The file is private, so it is fetched with the
// session cookie and shown from a temporary blob URL.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getReceiptFile, type Receipt } from "../api";
import { Alert } from "./Alert";
import { Spinner } from "./Spinner";

export function FilePreview({ receipt }: { receipt: Receipt }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["receipt-file", receipt.id],
    queryFn: () => getReceiptFile(receipt.id),
    enabled: receipt.has_original_file,
    staleTime: 5 * 60_000,
  });
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const u = URL.createObjectURL(data);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [data]);

  if (!receipt.has_original_file) {
    return <p className="text-sm text-slate-600">No original file is stored for this receipt.</p>;
  }
  if (isLoading) return <Spinner className="text-brand" label="Loading preview…" />;
  if (isError || !url) return <Alert kind="warning">The original file couldn't be loaded for preview.</Alert>;

  const isPdf = (receipt.file_mime_type ?? data?.type) === "application/pdf";
  return (
    <div>
      {isPdf ? (
        <iframe
          src={url}
          title={`Original PDF for receipt ${receipt.id}`}
          className="h-[28rem] w-full rounded-lg border border-slate-200 bg-white"
        />
      ) : (
        <img
          src={url}
          alt={`Original upload for receipt ${receipt.id}`}
          className="max-h-[32rem] w-full rounded-lg border border-slate-200 bg-white object-contain"
        />
      )}
      <a href={url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm font-semibold text-brand underline">
        Open original in a new tab
      </a>
    </div>
  );
}
