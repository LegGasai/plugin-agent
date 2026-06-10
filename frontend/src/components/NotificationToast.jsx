import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';

export function NotificationToast({ message, variant = 'info', onClose }) {
  if (!message) return null;
  const Icon = variant === 'error' ? AlertTriangle : variant === 'success' ? CheckCircle2 : Info;
  return (
    <aside className={`notification-toast ${variant}`} role={variant === 'error' ? 'alert' : 'status'} aria-live="polite">
      <span className="notification-toast-icon"><Icon size={16} /></span>
      <p>{message}</p>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="关闭提示">
          <X size={14} />
        </button>
      )}
    </aside>
  );
}
