import { useEffect, useRef } from 'react';
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';

export function NotificationToast({ message, variant = 'info', onClose, duration = 10000 }) {
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!message || !onCloseRef.current || !duration) return undefined;
    const timer = window.setTimeout(() => onCloseRef.current?.(), duration);
    return () => window.clearTimeout(timer);
  }, [duration, message]);

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
