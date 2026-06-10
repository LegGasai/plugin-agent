import { AlertTriangle, Info, X } from 'lucide-react';

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'danger',
  onConfirm,
  onCancel,
}) {
  if (!open) return null;
  const Icon = tone === 'info' ? Info : AlertTriangle;

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onCancel}>
      <section className={`confirm-dialog ${tone}`} role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="dialog-close-button" onClick={onCancel} aria-label="关闭弹窗">
          <X size={16} />
        </button>
        <div className={`dialog-icon ${tone}`}>
          <Icon size={20} />
        </div>
        <div className="dialog-copy">
          <h2 id="confirm-dialog-title">{title}</h2>
          <p>{description}</p>
        </div>
        <div className="dialog-actions">
          <button className="dialog-cancel-button" onClick={onCancel}>{cancelLabel}</button>
          <button className={`dialog-confirm-button ${tone}`} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </section>
    </div>
  );
}
