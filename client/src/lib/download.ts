// Downloads via fetch + blob (not a bare <a download>), so that the cookie is sent,
// the server's filename (Content-Disposition) is respected, and HTTP errors (401, 402
// premium_required, 503 ...) surface as readable messages instead of an error page.
import { parseErrorBody } from "../api";

export class DownloadError extends Error {
  status: number;
  code: string | null;
  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      /* fall through */
    }
  }
  const match = /filename="?([^";]+)"?/i.exec(header);
  return match ? match[1] : null;
}

export async function downloadFile(url: string, fallbackName = "download"): Promise<void> {
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* not JSON */
    }
    const info = parseErrorBody(res.status, body, `Download failed (${res.status})`);
    throw new DownloadError(
      res.status === 401 ? "Please sign in again to download this file." : info.message,
      res.status,
      info.code
    );
  }
  const blob = await res.blob();
  const name = filenameFromDisposition(res.headers.get("content-disposition")) ?? fallbackName;
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
