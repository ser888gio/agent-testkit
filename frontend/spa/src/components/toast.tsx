import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Tone = "success" | "danger";
interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

const ToastContext = createContext<(message: string, tone?: Tone) => void>(() => {});

export function useToast() {
  return useContext(ToastContext);
}

const DISMISS_MS = 4000;

function ToastItem({ toast, onDone }: { toast: Toast; onDone: (id: number) => void }) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDone(toast.id), DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [toast.id, onDone]);

  return (
    <li className={`toast toast-${toast.tone}`} data-testid="toast">
      <span>{toast.message}</span>
      <button type="button" aria-label="Dismiss notification" onClick={() => onDone(toast.id)}>
        &times;
      </button>
    </li>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((message: string, tone: Tone = "success") => {
    setToasts((current) => [...current, { id: Date.now() + Math.random(), message, tone }]);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      {/* aria-live rather than role="alert" per toast: one announcer that reads
          each arrival, instead of several competing for the screen reader. */}
      <ul className="toast-stack" role="status" aria-live="polite" data-testid="toast-stack">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDone={dismiss} />
        ))}
      </ul>
    </ToastContext.Provider>
  );
}
