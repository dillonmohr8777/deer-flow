"use client";

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  INSTALL_HELP_DISMISSED_KEY,
  type InstallPromptEvent,
  isInstalledWebApp,
  isIosDevice,
} from "@/core/pwa/install";

import styles from "./install-help.module.css";

const InstallHelpDialog = dynamic(
  () =>
    import("./install-help-dialog").then((module) => module.InstallHelpDialog),
  { ssr: false },
);

export function InstallHelp() {
  const pathname = usePathname();
  const [ios, setIos] = useState(false);
  const [installed, setInstalled] = useState(true);
  const [dismissed, setDismissed] = useState(false);
  const [open, setOpen] = useState(false);
  const [installPrompt, setInstallPrompt] = useState<InstallPromptEvent | null>(
    null,
  );
  const [prompting, setPrompting] = useState(false);
  const [promptFailed, setPromptFailed] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const displayMode = window.matchMedia("(display-mode: standalone)");
    const fullscreenMode = window.matchMedia("(display-mode: fullscreen)");
    const iosNavigator = navigator as Navigator & { standalone?: boolean };
    const updateInstalled = () => {
      setInstalled(
        isInstalledWebApp(
          displayMode.matches || fullscreenMode.matches,
          iosNavigator.standalone,
        ),
      );
    };
    setIos(
      isIosDevice(
        navigator.userAgent,
        navigator.platform,
        navigator.maxTouchPoints,
      ),
    );
    updateInstalled();
    try {
      setDismissed(localStorage.getItem(INSTALL_HELP_DISMISSED_KEY) === "1");
    } catch {
      // Installation remains usable when browser storage is disabled.
    }
    const onInstallPrompt = (event: Event) => {
      const promptEvent = event as InstallPromptEvent;
      if (typeof promptEvent.prompt !== "function") return;
      event.preventDefault();
      setInstallPrompt(promptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setInstallPrompt(null);
      setOpen(false);
    };
    displayMode.addEventListener("change", updateInstalled);
    fullscreenMode.addEventListener("change", updateInstalled);
    window.addEventListener("beforeinstallprompt", onInstallPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      displayMode.removeEventListener("change", updateInstalled);
      fullscreenMode.removeEventListener("change", updateInstalled);
      window.removeEventListener("beforeinstallprompt", onInstallPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  function dismiss() {
    setDismissed(true);
    setOpen(false);
    try {
      localStorage.setItem(INSTALL_HELP_DISMISSED_KEY, "1");
    } catch {
      // Dismiss for this visit even if persistence is unavailable.
    }
  }

  async function install() {
    if (!installPrompt || prompting) return;
    setPrompting(true);
    setPromptFailed(false);
    try {
      await installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      if (choice.outcome === "accepted") setOpen(false);
    } catch {
      setPromptFailed(true);
    } finally {
      setInstallPrompt(null);
      setPrompting(false);
    }
  }

  if (installed || dismissed || (!ios && !installPrompt && !promptFailed))
    return null;

  return (
    <aside
      aria-label="MomoBot installation"
      className={styles.hint}
      data-workspace={pathname?.startsWith("/workspace") || undefined}
    >
      <button
        ref={triggerRef}
        aria-haspopup="dialog"
        className={styles.trigger}
        onClick={() => setOpen(true)}
        type="button"
      >
        Install MomoBot
      </button>
      {open ? (
        <InstallHelpDialog
          ios={ios}
          nativePromptAvailable={installPrompt !== null}
          prompting={prompting}
          promptFailed={promptFailed}
          onOpenChange={setOpen}
          onInstall={() => void install()}
          onCloseFocus={() => triggerRef.current?.focus()}
        />
      ) : null}
      <button
        aria-label="Dismiss install help"
        className={styles.dismiss}
        onClick={dismiss}
        type="button"
      >
        ×
      </button>
    </aside>
  );
}
