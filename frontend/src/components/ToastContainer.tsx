import { useCallback, useEffect, useRef, useState } from "react";
import { TOAST_EVENT, type ToastPayload } from "../utils/notifications";

interface Toast extends ToastPayload {
  exiting: boolean;
}

const DURATION_MS = 4500;
const EXIT_MS = 300;

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const scheduleExit = useCallback((id: string) => {
    const t = setTimeout(() => {
      setToasts((prev) =>
        prev.map((toast) => (toast.id === id ? { ...toast, exiting: true } : toast)),
      );
      setTimeout(() => {
        setToasts((prev) => prev.filter((toast) => toast.id !== id));
        timers.current.delete(id);
      }, EXIT_MS);
    }, DURATION_MS);
    timers.current.set(id, t);
  }, []);

  const dismiss = useCallback(
    (id: string) => {
      const t = timers.current.get(id);
      if (t !== undefined) {
        clearTimeout(t);
        timers.current.delete(id);
      }
      setToasts((prev) =>
        prev.map((toast) => (toast.id === id ? { ...toast, exiting: true } : toast)),
      );
      setTimeout(() => {
        setToasts((prev) => prev.filter((toast) => toast.id !== id));
      }, EXIT_MS);
    },
    [],
  );

  useEffect(() => {
    const handler = (e: Event) => {
      const payload = (e as CustomEvent<ToastPayload>).detail;
      setToasts((prev) => [...prev, { ...payload, exiting: false }]);
      scheduleExit(payload.id);
    };
    window.addEventListener(TOAST_EVENT, handler);
    return () => window.removeEventListener(TOAST_EVENT, handler);
  }, [scheduleExit]);

  // Cleanup all timers on unmount
  useEffect(() => {
    return () => {
      timers.current.forEach(clearTimeout);
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast${toast.exiting ? " toast--exiting" : ""}`}
          role="alert"
          aria-live="assertive"
        >
          <div className="toast-content">
            <span className="toast-title">{toast.title}</span>
            {toast.body ? <span className="toast-body">{toast.body}</span> : null}
          </div>
          <button
            className="toast-close"
            aria-label="닫기"
            onClick={() => dismiss(toast.id)}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
