import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { NotificationDisplay, NotificationMode } from "../types";
import { setGlobalNotificationDisplay } from "../utils/notifications";

interface NotificationModeContextValue {
  mode: NotificationMode;
  setMode: (mode: NotificationMode) => void;
  display: NotificationDisplay;
  setDisplay: (display: NotificationDisplay) => void;
}

const NotificationModeContext = createContext<NotificationModeContextValue>({
  mode: "each",
  setMode: () => {},
  display: "toast",
  setDisplay: () => {},
});

const LS_KEY_MODE = "notification_mode";
const LS_KEY_DISPLAY = "notification_display";

function isValidMode(v: unknown): v is NotificationMode {
  return v === "each" || v === "all_done" || v === "none";
}

function isValidDisplay(v: unknown): v is NotificationDisplay {
  return v === "toast" || v === "browser" || v === "both";
}

export function NotificationModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<NotificationMode>(() => {
    const stored = localStorage.getItem(LS_KEY_MODE);
    return isValidMode(stored) ? stored : "each";
  });

  const [display, setDisplayState] = useState<NotificationDisplay>(() => {
    const stored = localStorage.getItem(LS_KEY_DISPLAY);
    return isValidDisplay(stored) ? stored : "toast";
  });

  useEffect(() => {
    void api
      .getSettings()
      .then((s) => {
        const m = s.notification_mode;
        if (isValidMode(m)) {
          localStorage.setItem(LS_KEY_MODE, m);
          setModeState(m);
        }
        const d = s.notification_display;
        if (isValidDisplay(d)) {
          localStorage.setItem(LS_KEY_DISPLAY, d);
          setDisplayState(d);
          setGlobalNotificationDisplay(d);
        }
      })
      .catch(() => {});
  }, []);

  // Keep module-level variable in sync
  useEffect(() => {
    setGlobalNotificationDisplay(display);
  }, [display]);

  const setMode = useCallback((m: NotificationMode) => {
    localStorage.setItem(LS_KEY_MODE, m);
    setModeState(m);
  }, []);

  const setDisplay = useCallback((d: NotificationDisplay) => {
    localStorage.setItem(LS_KEY_DISPLAY, d);
    setDisplayState(d);
    setGlobalNotificationDisplay(d);
  }, []);

  return (
    <NotificationModeContext.Provider value={{ mode, setMode, display, setDisplay }}>
      {children}
    </NotificationModeContext.Provider>
  );
}

export function useNotificationMode() {
  return useContext(NotificationModeContext);
}
