"use client";
import { useCallback, useEffect, useRef, useState } from "react";

type InspectOk = {
  email: string;
  workspace_name: string;
  expires_at: string;
  requires_login: boolean;
};

function getDetailMessage(data: unknown): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d && typeof (d as { message?: unknown }).message === "string")
      return (d as { message: string }).message;
  }
  return "Something went wrong. Please reopen the invite link and try again.";
}

function getCsrfHeader(): Record<string, string> {
  const m = typeof document !== "undefined" ? document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/) : null;
  if (m && m[1]) return { "X-CSRF-Token": decodeURIComponent(m[1]) };
  return {};
}

export default function InvitePage() {
  const initialized = useRef(false);
  const [token, setToken] = useState<string | null>(null);
  const [info, setInfo] = useState<InspectOk | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "inspect-error" | "accepting" | "done">("loading");
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const isNew = info ? !info.requires_login : false;

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const h = window.location.hash || "";
    const m = h.match(/#token=([^&]+)/);
    if (m && m[1]) {
      setToken(m[1]);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    } else {
      setStatus("inspect-error");
      setError("Missing invite token. Please reopen the invite link from your DM.");
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
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
        setInfo(data as InspectOk);
        setStatus("ready");
      } catch {
        if (!cancelled) {
          setStatus("inspect-error");
          setError("Could not load this invite. Please reopen the link and try again.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const accept = useCallback(async () => {
    if (!token || status === "accepting") return;
    setError("");
    if (isNew && password.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    if (isNew && password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setStatus("accepting");
    try {
      const res = await fetch("/api/v1/auth/invitations/accept", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...getCsrfHeader() },
        body: JSON.stringify({ token, password }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setStatus("ready");
        setError(getDetailMessage(data));
        return;
      }
      setStatus("done");
      window.location.assign("/workspace/command-center");
    } catch {
      setStatus("ready");
      setError("Could not accept this invite. Please try again.");
    }
  }, [token, password, confirm, isNew, status]);

  const busy = status === "loading" || status === "accepting";

  return (
    <main style={{ maxWidth: 480, margin: "48px auto", padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <meta name="referrer" content="no-referrer" />
      <h1>Workspace invite</h1>
      <p aria-live="polite" role="status">
        {status === "loading" ? "Loading invite…" : status === "accepting" ? "Accepting invite…" : status === "done" ? "Accepted. Redirecting…" : ""}
      </p>
      {error ? (
        <p role="alert" style={{ color: "#b00020" }}>
          {error}
        </p>
      ) : null}
      {info && status !== "inspect-error" ? (
        <section aria-label="Invite details">
          <p>
            <strong>{info.workspace_name}</strong>
          </p>
          <p>
            Invited: {info.email} · Expires: {new Date(info.expires_at).toLocaleString()}
          </p>
          <p>{isNew ? "Create a password of at least 12 characters to join." : "Enter your current account password to join this workspace."}</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void accept();
            }}
          >
            <div style={{ marginBottom: 12 }}>
              <label htmlFor="invite-password">{isNew ? "New password" : "Current password"}</label>
              <input
                id="invite-password"
                name="password"
                type="password"
                autoComplete={isNew ? "new-password" : "current-password"}
                minLength={isNew ? 12 : 1}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
                style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
              />
            </div>
            {isNew ? (
              <div style={{ marginBottom: 12 }}>
                <label htmlFor="invite-confirm">Confirm password</label>
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
                  style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
                />
              </div>
            ) : null}
            <button type="submit" disabled={busy || !token}>
              {status === "accepting" ? "Accepting…" : "Accept invite"}
            </button>
          </form>
        </section>
      ) : null}
    </main>
  );
}
