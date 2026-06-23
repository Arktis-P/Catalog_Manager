import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { NotificationMode } from "../types";

interface NotificationModeContextValue {
  mode: NotificationMode;
  setMode: (mode: NotificationMode) => void;
}

const NotificationModeContext = createContext<NotificationModeContextValue>({
  mode: "each",
  setMode: () => {},
});

const LS_KEY = "notification_mode";

function isValidMode(v: unknown): v is NotificationMode {
  return v === "each" || v === "all_done" || v === "none";
}

export function NotificationModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<NotificationMode>(() => {
    const stored = localStorage.getItem(LS_KEY);
    return isValidMode(stored) ? stored : "each";
  });

  useEffect(() => {
    void api
      .getSettings()
      .then((s) => {
        const m = s.notification_mode;
        if (isValidMode(m)) {
          localStorage.setItem(LS_KEY, m);
          setModeState(m);
        }
      })
      .catch(() => {});
  }, []);

  const setMode = useCallback((m: NotificationMode) => {
    localStorage.setItem(LS_KEY, m);
    setModeState(m);
  }, []);

  return (
    <NotificationModeContext.Provider value={{ mode, setMode }}>
      {children}
    </NotificationModeContext.Provider>
  );
}

export function useNotificationMode() {
  return useContext(NotificationModeContext);
}
