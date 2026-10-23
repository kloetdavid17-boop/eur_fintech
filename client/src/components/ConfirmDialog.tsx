import type { ReactNode } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      title={title}
      onClose={busy ? () => undefined : onCancel}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy}>
            {busy ? <Spinner label="Working…" /> : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm text-slate-700">{children}</div>
    </Modal>
  );
}
