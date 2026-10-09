"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";

import styles from "./install-help.module.css";

export function InstallHelpDialog({
  ios,
  nativePromptAvailable,
  prompting,
  promptFailed,
  onOpenChange,
  onInstall,
  onCloseFocus,
}: {
  ios: boolean;
  nativePromptAvailable: boolean;
  prompting: boolean;
  promptFailed: boolean;
  onOpenChange: (open: boolean) => void;
  onInstall: () => void;
  onCloseFocus: () => void;
}) {
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent
        className={styles.dialog}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          onCloseFocus();
        }}
      >
        <DialogTitle className={styles.title}>
          Keep MomoBot one tap away
        </DialogTitle>
        <DialogDescription>
          Open your private workspace from your Home Screen or desktop. An
          internet connection is required.
        </DialogDescription>
        {ios ? (
          <ol className={styles.steps}>
            <li>Open this site in Safari.</li>
            <li>Open the Share menu; it may be inside the page’s More menu.</li>
            <li>
              Choose Add to Home Screen. If it’s missing, check Edit Actions.
            </li>
            <li>Keep Open as Web App enabled, if shown, then tap Add.</li>
          </ol>
        ) : (
          <>
            <p>Use your browser’s install button to add MomoBot as an app.</p>
            {nativePromptAvailable ? (
              <button
                className={styles.primary}
                disabled={prompting}
                onClick={onInstall}
                type="button"
              >
                {prompting ? "Opening install prompt…" : "Install app"}
              </button>
            ) : null}
            {promptFailed ? (
              <p role="status">
                The install prompt is unavailable. Try your browser’s app
                installation menu.
              </p>
            ) : null}
          </>
        )}
        <p className={styles.note}>
          You may need to sign in again when you first open the installed app.
        </p>
        <button
          className={styles.secondary}
          onClick={() => onOpenChange(false)}
          type="button"
        >
          Got it
        </button>
      </DialogContent>
    </Dialog>
  );
}
