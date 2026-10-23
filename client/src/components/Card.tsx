import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "article" | "section";
}) {
  return (
    <Tag className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>{children}</Tag>
  );
}
