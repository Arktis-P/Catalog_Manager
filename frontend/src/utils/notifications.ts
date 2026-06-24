export type NotificationPermissionStatus = "granted" | "denied" | "default" | "unsupported";
export type NotificationDisplay = "toast" | "browser" | "both";

export const TOAST_EVENT = "app:toast" as const;

export interface ToastPayload {
  id: string;
  title: string;
  body?: string;
}

let _notificationDisplay: NotificationDisplay = "toast";

export function setGlobalNotificationDisplay(display: NotificationDisplay) {
  _notificationDisplay = display;
}

export function getGlobalNotificationDisplay(): NotificationDisplay {
  return _notificationDisplay;
}

export function getNotificationPermissionStatus(): NotificationPermissionStatus {
  if (!("Notification" in window)) return "unsupported";
  return Notification.permission;
}

export async function ensureNotificationPermission(): Promise<boolean> {
  if (!("Notification" in window)) {
    return false;
  }
  if (Notification.permission === "granted") {
    return true;
  }
  if (Notification.permission === "denied") {
    return false;
  }
  const result = await Notification.requestPermission();
  return result === "granted";
}

export function showTaskCompleteNotification(title: string, body?: string) {
  const display = _notificationDisplay;

  if (display === "browser" || display === "both") {
    if ("Notification" in window && Notification.permission === "granted") {
      try {
        new Notification(title, { body });
      } catch {
        // Ignore notification failures in unsupported environments.
      }
    }
  }

  if (display === "toast" || display === "both") {
    const payload: ToastPayload = {
      id: `${Date.now()}-${Math.random()}`,
      title,
      body,
    };
    window.dispatchEvent(new CustomEvent(TOAST_EVENT, { detail: payload }));
  }
}
