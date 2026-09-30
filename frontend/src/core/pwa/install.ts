export const INSTALL_HELP_DISMISSED_KEY = "momobot.install-help.dismissed.v1";

export interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

export function isIosDevice(
  userAgent: string,
  platform: string,
  maxTouchPoints: number,
): boolean {
  return (
    /iPad|iPhone|iPod/.test(userAgent) ||
    (platform === "MacIntel" && maxTouchPoints > 1)
  );
}

export function isInstalledWebApp(
  displayMode: boolean,
  iosStandalone: boolean | undefined,
): boolean {
  return displayMode || iosStandalone === true;
}

export async function registerPublicServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!window.isSecureContext || !("serviceWorker" in navigator)) return null;
  return navigator.serviceWorker.register("/sw.js", {
    scope: "/",
    updateViaCache: "none",
  });
}
