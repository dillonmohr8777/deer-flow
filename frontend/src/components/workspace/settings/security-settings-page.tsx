"use client";

import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetch, getCsrfHeaders } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { parseAuthError } from "@/core/auth/types";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

type Step = "idle" | "enrolling" | "confirming" | "recoveryCodes" | "disabling";

export function SecuritySettingsPage() {
  const { user, refreshUser } = useAuth();
  const { t } = useI18n();

  const [step, setStep] = useState<Step>("idle");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [secret, setSecret] = useState("");
  const [otpauthUri, setOtpauthUri] = useState("");
  const [code, setCode] = useState("");

  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);

  const [password, setPassword] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);

  const resetToIdle = () => {
    setStep("idle");
    setSecret("");
    setOtpauthUri("");
    setCode("");
    setRecoveryCodes([]);
    setCopied(false);
    setPassword("");
    setDisableCode("");
    setUseRecoveryCode(false);
    setError("");
  };

  const startEnroll = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/mfa/enroll/start", {
        method: "POST",
        headers: getCsrfHeaders(),
      });
      if (!res.ok) {
        const data = await res.json();
        setError(parseAuthError(data).message);
        return;
      }
      const data = (await res.json()) as {
        secret: string;
        otpauth_uri: string;
      };
      setSecret(data.secret);
      setOtpauthUri(data.otpauth_uri);
      setStep("enrolling");
    } catch {
      setError(t.settings.security.networkError);
    } finally {
      setLoading(false);
    }
  };

  const confirmEnroll = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/mfa/enroll/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) {
        const data = await res.json();
        setError(
          parseAuthError(data).message || t.settings.security.enrollInvalidCode,
        );
        return;
      }
      const data = (await res.json()) as { recovery_codes: string[] };
      setRecoveryCodes(data.recovery_codes);
      setStep("recoveryCodes");
      void refreshUser();
    } catch {
      setError(t.settings.security.networkError);
    } finally {
      setLoading(false);
    }
  };

  const copyRecoveryCodes = async () => {
    const ok = await writeTextToClipboard(recoveryCodes.join("\n"));
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const disableMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/mfa/disable", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
        body: JSON.stringify({
          password,
          ...(useRecoveryCode
            ? { recovery_code: disableCode }
            : { code: disableCode }),
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        setError(
          parseAuthError(data).message || t.settings.security.disableIncorrect,
        );
        return;
      }
      void refreshUser();
      resetToIdle();
    } catch {
      setError(t.settings.security.networkError);
    } finally {
      setLoading(false);
    }
  };

  if (step === "recoveryCodes") {
    return (
      <SettingsSection
        title={t.settings.security.recoveryCodesTitle}
        description={t.settings.security.recoveryCodesDescription}
      >
        <div className="max-w-sm space-y-3">
          <div className="bg-muted grid grid-cols-2 gap-2 rounded-md p-3 font-mono text-sm">
            {recoveryCodes.map((rc) => (
              <span key={rc}>{rc}</span>
            ))}
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void copyRecoveryCodes()}
            >
              {copied
                ? t.settings.security.recoveryCodesCopied
                : t.settings.security.recoveryCodesCopyButton}
            </Button>
            <Button type="button" size="sm" onClick={resetToIdle}>
              {t.settings.security.recoveryCodesDoneButton}
            </Button>
          </div>
        </div>
      </SettingsSection>
    );
  }

  if (step === "enrolling") {
    return (
      <SettingsSection
        title={t.settings.security.enrollScanTitle}
        description={t.settings.security.enrollScanInstructions}
      >
        <form onSubmit={confirmEnroll} className="max-w-sm space-y-3">
          <div className="inline-block rounded-md bg-white p-3">
            <QRCodeSVG value={otpauthUri} size={180} />
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm">
              {t.settings.security.enrollManualEntryLabel}
            </p>
            <code className="block text-sm break-all">{secret}</code>
          </div>
          <Input
            type="text"
            inputMode="numeric"
            placeholder={t.settings.security.enrollCodePlaceholder}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            minLength={6}
            maxLength={6}
          />
          {error && <p className="text-sm text-red-500">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={loading}>
              {t.settings.security.enrollConfirmButton}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={resetToIdle}
            >
              {t.settings.security.enrollCancelButton}
            </Button>
          </div>
        </form>
      </SettingsSection>
    );
  }

  if (step === "disabling") {
    return (
      <SettingsSection title={t.settings.security.disableTitle}>
        <form onSubmit={disableMfa} className="max-w-sm space-y-3">
          <Input
            type="password"
            placeholder={t.settings.security.disablePasswordLabel}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <Input
            type="text"
            placeholder={
              useRecoveryCode
                ? t.settings.security.disableRecoveryCodeLabel
                : t.settings.security.disableCodeLabel
            }
            value={disableCode}
            onChange={(e) => setDisableCode(e.target.value)}
            required
          />
          <button
            type="button"
            className="text-muted-foreground text-sm hover:underline"
            onClick={() => {
              setUseRecoveryCode(!useRecoveryCode);
              setDisableCode("");
            }}
          >
            {useRecoveryCode
              ? t.settings.security.disableUseCodeLink
              : t.settings.security.disableUseRecoveryCodeLink}
          </button>
          {error && <p className="text-sm text-red-500">{error}</p>}
          <div className="flex gap-2">
            <Button
              type="submit"
              variant="destructive"
              size="sm"
              disabled={loading}
            >
              {t.settings.security.disableSubmitButton}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={resetToIdle}
            >
              {t.settings.security.disableCancelButton}
            </Button>
          </div>
        </form>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title={t.settings.security.title}
      description={t.settings.security.description}
    >
      <div className="max-w-sm space-y-3">
        <p className="text-sm font-medium">
          {user?.mfa_enabled
            ? t.settings.security.statusEnabled
            : t.settings.security.statusDisabledDescription}
        </p>
        {error && <p className="text-sm text-red-500">{error}</p>}
        {user?.mfa_enabled ? (
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => setStep("disabling")}
          >
            {t.settings.security.disableButton}
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            disabled={loading}
            onClick={() => void startEnroll()}
          >
            {t.settings.security.enableButton}
          </Button>
        )}
      </div>
    </SettingsSection>
  );
}
