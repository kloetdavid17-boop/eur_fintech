import type { ReactNode } from "react";
import { PiCheckCircle, PiInfo, PiWarning, PiWarningCircle } from "react-icons/pi";

type Kind = "info" | "success" | "warning" | "error";

const STYLES: Record<Kind, { box: string; icon: string; Icon: typeof PiInfo }> = {
  info: { box: "border-blue-200 bg-blue-50 text-blue-950", icon: "text-blue-700", Icon: PiInfo },
  success: {
    box: "border-emerald-200 bg-emerald-50 text-emerald-950",
    icon: "text-emerald-700",
    Icon: PiCheckCircle,
  },
  warning: {
    box: "border-amber-300 bg-amber-50 text-amber-950",
    icon: "text-amber-700",
    Icon: PiWarning,
  },
  error: { box: "border-red-200 bg-red-50 text-red-950", icon: "text-red-700", Icon: PiWarningCircle },
};

/** Errors use role="alert" (announced immediately); everything else role="status". */
export function Alert({
  kind = "info",
  title,
  children,
  action,
  className = "",
}: {
  kind?: Kind;
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const { box, icon, Icon } = STYLES[kind];
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={`flex gap-3 rounded-lg border p-3 text-sm ${box} ${className}`}
    >
      <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${icon}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={title ? "mt-0.5" : ""}>{children}</div> : null}
        {action ? <div className="mt-2">{action}</div> : null}
      </div>
    </div>
  );
}
