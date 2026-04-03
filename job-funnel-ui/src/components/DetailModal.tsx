import type { ReactNode } from "react";

interface DetailModalProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
  previousDisabled?: boolean;
  nextDisabled?: boolean;
  children: ReactNode;
}

export function DetailModal({
  title,
  subtitle,
  onClose,
  onPrevious,
  onNext,
  previousDisabled = false,
  nextDisabled = false,
  children,
}: DetailModalProps) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-shell">
        <div className="modal-toolbar">
          <div className="modal-nav-actions">
            <button type="button" className="icon-button" onClick={onPrevious} disabled={!onPrevious || previousDisabled}>
              ←
            </button>
            <button type="button" className="icon-button" onClick={onNext} disabled={!onNext || nextDisabled}>
              →
            </button>
          </div>

          <button type="button" className="icon-button" onClick={onClose} aria-label="Close detail view">
            ×
          </button>
        </div>

        <div className="detail-header">
          <h3>{title}</h3>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>

        <div className="modal-content">{children}</div>
      </div>
    </div>
  );
}
