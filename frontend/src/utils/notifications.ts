export type NotificationPermissionStatus = "granted" | "denied" | "default" | "unsupported";

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
  if (!("Notification" in window) || Notification.permission !== "granted") {
    return;
  }
  try {
    new Notification(title, { body });
  } catch {
    // Ignore notification failures in unsupported environments.
  }
}
