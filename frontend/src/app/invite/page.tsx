"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { brandMotionAllowed } from "@/components/workspace/command-center/appearance-preferences";

import {
  clearStashedInviteToken,
  passwordSignInUrl,
  signedInAsInvitee,
  ssoStartUrl,
  stashInviteToken,
  takeStashedInviteToken,
  type InviteInfo,
} from "./invite-mode";

import styles from "./invite.module.css";

type SsoProvider = { id: string; display_name: string };

// Highest-emotion moment in the funnel: the pin lifts, the sheet tilts and
// slides away, 420ms. Gated the same way as S04's other moment (cut-paper):
// prefers-reduced-motion turns it fully off, not reduced.
const RELEASE_MS = 420;

function releaseAllowed(): boolean {
  if (typeof window === "undefined") return false;
  return brandMotionAllowed({
    motion: true,
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)")
      .matches,
    visible: document.visibilityState === "visible",
    inView: true,
  });
}

function getDetailMessage(data: unknown): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (
      d &&
      typeof d === "object" &&
      "message" in d &&
      typeof (d as { message?: unknown }).message === "string"
    )
      return (d as { message: string }).message;
  }
  return "Something went wrong. Please reopen the invite link and try again.";
}

function getCsrfHeader(): Record<string, string> {
  const m =
    typeof document !== "undefined"
      ? /(?:^|;\s*)csrf_token=([^;]+)/.exec(document.cookie)
      : null;
  if (m?.[1]) return { "X-CSRF-Token": decodeURIComponent(m[1]) };
  return {};
}

export default function InvitePage() {
  const initialized = useRef(false);
  // The token lives only here once the page has it: never in a URL, and in
  // sessionStorage only for the moment of a sign-in trip.
  const [token, setToken] = useState<string | null>(null);
  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [status, setStatus] = useState<
    "loading" | "ready" | "inspect-error" | "accepting" | "done"
  >("loading");
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [providers, setProviders] = useState<SsoProvider[]>([]);
  // undefined = not checked yet, null = not signed in.
  const [sessionEmail, setSessionEmail] = useState<string | null | undefined>(
    undefined,
  );
  // "new": no account yet, so create one here. "existing": sign in, then
  // accept with that session.
  const mode = info ? (info.requires_login ? "existing" : "new") : null;
  const isNew = mode === "new";
  const isExisting = mode === "existing";
  const signedIn =
    isExisting && !!info && signedInAsInvitee(sessionEmail, info.email);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    // Any stash from an earlier sign-in trip is read once and removed right
    // away, whichever token wins, so it never outlives this page load.
    const stashed = takeStashedInviteToken();
    const m = /#token=([^&]+)/.exec(window.location.hash || "");
    if (m?.[1]) {
      setToken(m[1]);
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    } else if (stashed) {
      setToken(stashed);
    } else {
      setStatus("inspect-error");
      setError(
        "Missing invite token. Please reopen the invite link from your DM.",
      );
    }
  }, []);

  useEffect(() => {
    // Back from an abandoned sign-in (Back button, page restored from the
    // back-forward cache without remounting): the token is still in state,
    // so the stash left for that trip can go now.
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) clearStashedInviteToken();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/v1/auth/invitations/inspect", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...getCsrfHeader() },
          body: JSON.stringify({ token }),
        });
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok) {
          setStatus("inspect-error");
          setError(getDetailMessage(data));
          return;
        }
        setInfo(data as InviteInfo);
        setStatus("ready");
      } catch {
        if (!cancelled) {
          setStatus("inspect-error");
          setError(
            "Couldn't load this invite. Please reopen the link and try again.",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!mode) return;
    let cancelled = false;
    void fetch("/api/v1/auth/providers")
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { providers?: SsoProvider[] } | null) => {
        if (!cancelled && Array.isArray(data?.providers)) {
          setProviders(data.providers);
        }
      })
      .catch(() => {
        // No SSO buttons; the password paths still work.
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  useEffect(() => {
    if (mode !== "existing") return;
    let cancelled = false;
    void fetch("/api/v1/auth/me", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { email?: unknown } | null) => {
        if (cancelled) return;
        setSessionEmail(typeof data?.email === "string" ? data.email : null);
      })
      .catch(() => {
        if (!cancelled) setSessionEmail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  // The only two ways off this page mid-invite. Each re-stashes the token
  // just before leaving, so the page can pick it up again on the way back.
  const startSso = useCallback(
    (providerId: string) => {
      if (!token) return;
      stashInviteToken(token);
      window.location.assign(ssoStartUrl(providerId));
    },
    [token],
  );

  const startPasswordSignIn = useCallback(() => {
    if (token) stashInviteToken(token);
  }, [token]);

  const accept = useCallback(async () => {
    if (!token || !mode || status === "accepting") return;
    if (isExisting && !signedIn) return;
    setError("");
    if (isNew && password.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    if (isNew && password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setStatus("accepting");
    try {
      const res = await fetch("/api/v1/auth/invitations/accept", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...getCsrfHeader() },
        // An existing account proves itself with its session; only a new
        // account sends the password it is creating.
        body: JSON.stringify(isNew ? { token, password } : { token }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setStatus("ready");
        setError(getDetailMessage(data));
        return;
      }
      clearStashedInviteToken();
      setStatus("done");
      // The release moment (pin lifts, sheet tilts and slides away) gets
      // its 420ms before the navigation cuts it short. Reduced motion (or
      // no window, e.g. under test) skips straight to the redirect.
      if (releaseAllowed()) {
        window.setTimeout(() => {
          window.location.assign("/workspace/command-center");
        }, RELEASE_MS);
      } else {
        window.location.assign("/workspace/command-center");
      }
    } catch {
      setStatus("ready");
      setError("Couldn't accept this invite. Please try again.");
    }
  }, [token, mode, password, confirm, isNew, isExisting, signedIn, status]);

  const busy = status === "loading" || status === "accepting";
  const released = status === "done";

  return (
    <main className={styles.field} data-treatment="paper">
      <div
        className={[
          styles.frame,
          "pinned",
          released ? styles.sheetReleased : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {error ? <span className={styles.errorTag} aria-hidden="true" /> : null}
        <div
          className={[
            styles.sheet,
            "sheet",
            "paper-torn",
            error ? styles.sheetError : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <meta name="referrer" content="no-referrer" />
          <h1 className={`${styles.title} m-voice-serif-bold`}>
            {info
              ? `You're invited to ${info.workspace_name} on MomoBot`
              : "Your MomoBot invite"}
          </h1>
          <p
            aria-live="polite"
            role="status"
            className={`${styles.status} m-voice-body`}
          >
            {status === "loading"
              ? "Loading invite…"
              : status === "accepting"
                ? "Accepting invite…"
                : status === "done"
                  ? "Accepted. Redirecting…"
                  : ""}
          </p>
          {error ? (
            <p role="alert" className={`${styles.errorText} m-voice-body`}>
              {error}
            </p>
          ) : null}
          {status === "inspect-error" ? (
            <p className={`${styles.hint} m-voice-body`}>
              Already a member?{" "}
              <Link className={styles.link} href="/login">
                Sign in instead
              </Link>
            </p>
          ) : null}
          {info && status !== "inspect-error" ? (
            <section aria-label="Invite details" className={styles.details}>
              <p className={`${styles.email} m-voice-body`}>
                Invited: {info.email} · Expires:{" "}
                {new Date(info.expires_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </p>
              <p className={`${styles.hint} m-voice-body`}>
                {isNew
                  ? "Create a password of at least 12 characters to join."
                  : sessionEmail === undefined
                    ? "Checking your sign-in…"
                    : signedIn
                      ? `You're signed in as ${info.email}. Accept to join.`
                      : sessionEmail
                        ? `You're signed in as ${sessionEmail}, but this invite is for ${info.email}. Sign in as ${info.email} to accept.`
                        : `Sign in as ${info.email} to accept.`}
              </p>
              {isNew ? (
                <>
                  <form
                    className={styles.form}
                    onSubmit={(e) => {
                      e.preventDefault();
                      void accept();
                    }}
                  >
                    <div className={styles.field2}>
                      <label
                        htmlFor="invite-password"
                        className={`${styles.label} m-voice-label`}
                      >
                        New password
                      </label>
                      <input
                        id="invite-password"
                        name="password"
                        type="password"
                        autoComplete="new-password"
                        minLength={12}
                        required
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        disabled={busy}
                        className={styles.input}
                      />
                    </div>
                    <div className={styles.field2}>
                      <label
                        htmlFor="invite-confirm"
                        className={`${styles.label} m-voice-label`}
                      >
                        Confirm password
                      </label>
                      <input
                        id="invite-confirm"
                        name="confirm"
                        type="password"
                        autoComplete="new-password"
                        minLength={12}
                        required
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                        disabled={busy}
                        className={styles.input}
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={busy || !token}
                      className={styles.submit}
                    >
                      {status === "accepting" ? "Accepting…" : "Accept invite"}
                    </button>
                  </form>
                  {providers.length > 0 ? (
                    <>
                      <p className={`${styles.hint} m-voice-body`}>
                        Or skip the password: sign in with {info.email}.
                      </p>
                      <SignInOptions providers={providers} onSso={startSso} />
                    </>
                  ) : null}
                </>
              ) : signedIn ? (
                <form
                  className={styles.form}
                  onSubmit={(e) => {
                    e.preventDefault();
                    void accept();
                  }}
                >
                  <button
                    type="submit"
                    disabled={busy || !token}
                    className={styles.submit}
                  >
                    {status === "accepting" ? "Accepting…" : "Accept invite"}
                  </button>
                </form>
              ) : sessionEmail === undefined ? null : (
                <SignInOptions
                  providers={providers}
                  onSso={startSso}
                  onPasswordSignIn={startPasswordSignIn}
                />
              )}
            </section>
          ) : null}
        </div>
      </div>
    </main>
  );
}

/**
 * Ways to sign in and come back to /invite. Each one stashes the token right
 * before the page is left; neither puts it in a URL.
 */
function SignInOptions({
  providers,
  onSso,
  onPasswordSignIn,
}: {
  providers: SsoProvider[];
  onSso: (providerId: string) => void;
  /** Offered to existing accounts; a new invitee creates a password above. */
  onPasswordSignIn?: () => void;
}) {
  return (
    <div className={styles.ssoList}>
      {providers.map((provider) => (
        <button
          key={provider.id}
          type="button"
          className={styles.sso}
          onClick={() => onSso(provider.id)}
        >
          Continue with {provider.display_name}
        </button>
      ))}
      {onPasswordSignIn ? (
        <Link
          className={styles.sso}
          href={passwordSignInUrl()}
          onClick={onPasswordSignIn}
        >
          Sign in with password
        </Link>
      ) : null}
    </div>
  );
}
