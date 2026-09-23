"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import inviteStyles from "@/app/invite/invite.module.css";
import { RememberSessionOption } from "@/components/auth/remember-session-option";
import { MomoFilm } from "@/components/momentum/momo-film";
import { useIntroMotion } from "@/components/momentum/momobot/intro-motion";
import { MomoBotLockup } from "@/components/momentum/momobot/lockup";
import momoStyles from "@/components/momentum/momobot/momobot.module.css";
import { ScrapbookBackdrop } from "@/components/momentum/momobot/scrapbook-backdrop";
import { resolveFunnelTreatment } from "@/components/momentum/treatment";
import { Button } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { resolveAuthNextPath } from "@/core/auth/next-path";
import {
  loadRememberLoginPreference,
  saveRememberLoginPreference,
} from "@/core/auth/remember-login";
import {
  canCreateRegularAccount,
  fetchSetupStatus,
  type SetupStatusResponse,
} from "@/core/auth/setup";
import { parseAuthError } from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useAuth();
  const { theme, resolvedTheme } = useTheme();
  const { t } = useI18n();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [isLogin, setIsLogin] = useState(true);
  const [ssoProviders, setSsoProviders] = useState<
    { id: string; display_name: string; type: string }[]
  >([]);
  const [setupStatus, setSetupStatus] = useState<SetupStatusResponse | null>(
    null,
  );
  const [setupStatusPhase, setSetupStatusPhase] = useState<
    "checking" | "ready" | "unavailable"
  >("checking");
  const [setupStatusAttempt, setSetupStatusAttempt] = useState(0);

  // Extract error from query params (e.g., ?error=sso_failed)
  const errorParam = searchParams.get("error");
  const [error, setError] = useState(
    errorParam
      ? (t.login.errors[errorParam as keyof typeof t.login.errors] ??
          t.login.authFailed)
      : "",
  );
  // Soft hint shown after a failed login when SSO is configured: an SSO-only
  // account has no local password, so the backend returns a generic
  // "incorrect email or password" (deliberately, to avoid account enumeration).
  // Nudge the user toward the SSO buttons without confirming the account exists.
  const [showSsoHint, setShowSsoHint] = useState(false);
  const [loading, setLoading] = useState(false);
  // Momo's Hello film plays while motion is allowed (reduced motion, hidden
  // tab and pause are decided inside) and holds its poster otherwise.
  const introMotion = useIntroMotion();

  // Get next parameter for validated redirect
  const nextParam = searchParams.get("next");
  const redirectPath = resolveAuthNextPath(nextParam);
  const regularSignupAllowed = canCreateRegularAccount({
    // A failed probe must not expose registration while the system's setup
    // state is unknown. Existing users can still sign in normally.
    checked: setupStatusPhase === "ready",
    status: setupStatus,
  });
  const systemNeedsAdminSetup = setupStatus?.needs_setup === true;
  const showSetupStatusUnavailable =
    setupStatusPhase === "unavailable" ||
    (setupStatusAttempt > 0 && setupStatusPhase === "checking");

  // Redirect if already authenticated (client-side, post-login)
  useEffect(() => {
    if (isAuthenticated) {
      router.push(redirectPath);
    }
  }, [isAuthenticated, redirectPath, router]);

  useEffect(() => {
    const preference = loadRememberLoginPreference();
    setRememberMe(preference.rememberMe);
    if (preference.email) {
      setEmail(preference.email);
    }
  }, []);

  // Fetch setup state independently so retrying a slow Gateway does not also
  // refetch unrelated auth-provider configuration.
  useEffect(() => {
    let cancelled = false;
    setSetupStatusPhase("checking");

    void fetchSetupStatus()
      .then((data) => {
        if (cancelled) return;
        setSetupStatus(data);
        setSetupStatusPhase("ready");
        if (data.needs_setup) {
          setIsLogin(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSetupStatus(null);
          setSetupStatusPhase("unavailable");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [setupStatusAttempt]);

  // SSO providers are static for the page lifetime and should not be coupled to
  // setup-status retries.
  useEffect(() => {
    let cancelled = false;

    void fetch("/api/v1/auth/providers")
      .then((r) => r.json())
      .then(
        (data: {
          providers: { id: string; display_name: string; type: string }[];
        }) => {
          if (!cancelled) {
            setSsoProviders(data.providers ?? []);
          }
        },
      )
      .catch(() => {
        // Ignore errors; no SSO providers shown
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setShowSsoHint(false);
    setLoading(true);

    if (!isLogin && !regularSignupAllowed) {
      setError(t.login.adminSetupRequiredDescription);
      setLoading(false);
      return;
    }

    try {
      const endpoint = isLogin
        ? "/api/v1/auth/login/local"
        : "/api/v1/auth/register";
      const body = isLogin
        ? new URLSearchParams({
            password,
            remember_me: String(rememberMe),
            username: email,
          })
        : JSON.stringify({ email, password, remember_me: rememberMe });

      const headers: HeadersInit = isLogin
        ? { "Content-Type": "application/x-www-form-urlencoded" }
        : { "Content-Type": "application/json" };

      const res = await fetch(endpoint, {
        method: "POST",
        headers,
        body,
        credentials: "include", // Important: include HttpOnly cookie
      });

      if (!res.ok) {
        const data = await res.json();
        const authError = parseAuthError(data);
        setError(authError.message);
        // On a failed login with SSO configured, surface a hint pointing at the
        // SSO buttons — the "wrong password" may really mean "this is an SSO account".
        if (isLogin && ssoProviders.length > 0) {
          setShowSsoHint(true);
        }
        return;
      }

      saveRememberLoginPreference({ email, rememberMe });

      // Both login and register set a cookie — redirect to workspace
      router.push(redirectPath);
    } catch {
      setError(t.login.networkError);
    } finally {
      setLoading(false);
    }
  };

  // Same gate as `/` and `/invite`: FUNNEL_TREATMENT decides the default,
  // `?look=paper|current` previews either. Under "current" every class below
  // is the pre-paper sign-in, unchanged.
  const paper = resolveFunnelTreatment(searchParams.toString()) === "paper";
  const actualTheme = theme === "system" ? resolvedTheme : theme;
  const mutedClass = paper ? undefined : "text-muted-foreground";
  const mutedStyle = paper ? { color: "var(--paper-ink-muted)" } : undefined;
  const linkClass = paper ? undefined : "text-blue-500";
  const linkStyle = paper ? { color: "var(--paper-focus)" } : undefined;

  // Paper: the sign-in is the same physical object as the invite — one
  // deckled cream sheet pinned on the blueprint field (invite.module.css
  // .field/.frame/.sheet). No flickering grid, no motion: the static
  // composition is the thesis for this surface. Auth logic is untouched.
  const card = (
    <div
      className={cn(
        "relative w-full max-w-md space-y-6",
        paper
          ? cn(inviteStyles.sheet, "sheet paper-torn")
          : "border-border/20 bg-background/5 rounded-3xl border p-8 backdrop-blur-sm",
      )}
    >
      <div className="text-center">
        <MomoBotLockup
          className="mx-auto"
          wordmarkClassName={cn(!paper && "dark:brightness-0 dark:invert")}
        />
        <h1
          className={cn("mt-2", mutedClass, paper && "m-voice-serif text-lg")}
          style={mutedStyle}
        >
          {isLogin ? t.login.signInTitle : t.login.createAccountTitle}
        </h1>
      </div>

      {showSetupStatusUnavailable && (
        <div
          role="status"
          aria-live="polite"
          className="border-l-2 border-amber-500 ps-3 text-sm"
        >
          <p className="font-medium">{t.login.serviceUnavailableTitle}</p>
          <p className={cn("mt-1", mutedClass)} style={mutedStyle}>
            {t.login.serviceUnavailableDescription}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-3"
            disabled={setupStatusPhase === "checking"}
            onClick={() => {
              setSetupStatusPhase("checking");
              setSetupStatusAttempt((attempt) => attempt + 1);
            }}
          >
            {setupStatusPhase === "checking"
              ? t.login.pleaseWait
              : t.login.retry}
          </Button>
        </div>
      )}

      {systemNeedsAdminSetup && (
        <div className="border-l-2 border-blue-500 ps-3 text-sm">
          <p className="font-medium">{t.login.adminSetupRequiredTitle}</p>
          <p className={cn("mt-1", mutedClass)} style={mutedStyle}>
            {t.login.adminSetupRequiredDescription}
          </p>
          <Link
            href="/setup"
            className={cn(
              "mt-2 inline-block font-medium hover:underline",
              linkClass,
            )}
            style={linkStyle}
          >
            {t.login.createAdminAccount}
          </Link>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="flex flex-col space-y-1">
          <label htmlFor="email" className="text-sm font-medium">
            {t.login.email}
          </label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t.login.emailPlaceholder}
            required
          />
        </div>
        <div className="flex flex-col space-y-1">
          <label htmlFor="password" className="text-sm font-medium">
            {t.login.password}
          </label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t.login.passwordPlaceholder}
            required
            minLength={isLogin ? 6 : 8}
          />
        </div>

        <RememberSessionOption
          checked={rememberMe}
          onCheckedChange={setRememberMe}
        />

        {error && <p className="text-sm text-red-500">{error}</p>}

        <Button
          type="submit"
          className="w-full"
          disabled={loading}
          style={
            paper
              ? {
                  background: "var(--paper-royal)",
                  color: "var(--paper-cream-hi)",
                }
              : undefined
          }
        >
          {loading
            ? t.login.pleaseWait
            : isLogin
              ? t.login.signIn
              : t.login.createAccount}
        </Button>
      </form>

      {ssoProviders.length > 0 && (
        <div className="space-y-2">
          {isLogin && (
            <div className="relative my-4">
              <div className="absolute inset-0 flex items-center">
                <span
                  className="w-full border-t"
                  style={
                    paper ? { borderColor: "var(--paper-line)" } : undefined
                  }
                />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span
                  className={cn(
                    "px-2",
                    !paper && "bg-background text-muted-foreground",
                  )}
                  style={
                    paper
                      ? {
                          background: "var(--paper-cream-hi)",
                          color: "var(--paper-ink-muted)",
                        }
                      : undefined
                  }
                >
                  {t.login.orContinueWith}
                </span>
              </div>
            </div>
          )}
          {showSsoHint && (
            <p
              className={cn("text-center text-sm", mutedClass)}
              style={mutedStyle}
            >
              {t.login.ssoHint}
            </p>
          )}
          {ssoProviders.map((provider) => (
            <Button
              key={provider.id}
              type="button"
              variant="outline"
              className="w-full"
              disabled={loading}
              onClick={() => {
                window.location.href = `/api/v1/auth/oauth/${provider.id}?next=${encodeURIComponent(redirectPath)}&remember_me=${String(rememberMe)}`;
              }}
            >
              {t.login.continueWith(provider.display_name)}
            </Button>
          ))}
        </div>
      )}

      {regularSignupAllowed && (
        <div className="text-center text-sm">
          <button
            type="button"
            onClick={() => {
              setIsLogin(!isLogin);
              setError("");
              setShowSsoHint(false);
            }}
            className={cn("hover:underline", linkClass)}
            style={linkStyle}
          >
            {isLogin ? t.login.noAccountSignUp : t.login.haveAccountSignIn}
          </button>
        </div>
      )}

      <div className={cn("text-center text-xs", mutedClass)} style={mutedStyle}>
        <Link href="/" className="hover:underline">
          {t.login.backToHome}
        </Link>
      </div>
    </div>
  );

  return (
    <div
      className={cn(
        "relative min-h-screen overflow-x-hidden overflow-y-auto",
        paper
          ? inviteStyles.field
          : "bg-background flex items-center justify-center",
      )}
      data-treatment={paper ? "paper" : "current"}
    >
      {paper ? (
        <>
          <ScrapbookBackdrop motion={introMotion} tone="royal" />
          <div
            className={cn(
              inviteStyles.frame,
              "pinned",
              momoStyles.frameWithMomo,
            )}
          >
            <div className={momoStyles.momoPhoto}>
              <MomoFilm name="momo-hello" live={introMotion.live} />
            </div>
            {card}
          </div>
        </>
      ) : (
        <>
          <FlickeringGrid
            className="absolute inset-0 z-0 [mask-image:radial-gradient(60vh_60vh_at_50%_42%,black,transparent_72%)]"
            squareSize={4}
            gridGap={4}
            color={actualTheme === "dark" ? "white" : "black"}
            maxOpacity={0.22}
            flickerChance={0.2}
          />
          {card}
        </>
      )}
    </div>
  );
}
