"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import styles from "./page-body.module.css";

export { styles as pageStyles };

/**
 * Canon Momo artwork by role. Referenced by path only: the files under
 * public/momentum/momos/ are owned and redrawn elsewhere.
 */
const MOMO_ART = {
  analytics: "/momentum/momos/analytics.svg",
  builder: "/momentum/momos/builder.svg",
  engineer: "/momentum/momos/engineer.svg",
  lead: "/momentum/momos/lead.svg",
  qa: "/momentum/momos/qa.svg",
  reliability: "/momentum/momos/reliability.svg",
  research: "/momentum/momos/research.svg",
  verifier: "/momentum/momos/verifier.svg",
} as const;

export type MomoRole = keyof typeof MOMO_ART;

/** Loading: working squares that tick, and the same state in words. */
export function WorkingState({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <div role="status" className={cn(styles.working, className)}>
      <span className={styles.squares} aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span>{label}</span>
    </div>
  );
}

/** Error: a red-thread tag, the plain reason, and one next step. */
export function ErrorState({
  message,
  detail,
  action,
  className,
}: {
  message: string;
  detail?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div role="alert" className={cn(styles.error, className)}>
      <svg
        className={styles.errorTag}
        viewBox="0 0 56 36"
        aria-hidden="true"
        data-error-tag=""
      >
        <path
          className={styles.tagBody}
          d="M24 5h26a3 3 0 0 1 3 3v20a3 3 0 0 1-3 3H24l-7-6.5v-13z"
        />
        <circle className={styles.tagBody} cx="23.5" cy="18" r="2.2" />
        <path
          className={styles.thread}
          d="M23.5 18C15 17 12 7 4 9M23.5 18c-7 3-9 12-17 13"
        />
      </svg>
      <div className="min-w-0">
        <p className={styles.stateMessage}>{message}</p>
        {detail ? <p className={styles.stateDetail}>{detail}</p> : null}
        {action ? <div className={styles.stateAction}>{action}</div> : null}
      </div>
    </div>
  );
}

/** Empty: a small Momo holding a tool, one helpful sentence, one action. */
export function EmptyState({
  momo,
  title,
  children,
  action,
  className,
}: {
  momo: MomoRole;
  title?: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn(styles.empty, className)} data-empty-state="">
      <img
        className={styles.emptyMomo}
        src={MOMO_ART[momo]}
        alt=""
        aria-hidden="true"
        width={56}
        height={56}
      />
      <div className="min-w-0">
        {title ? <p className={styles.stateMessage}>{title}</p> : null}
        <p className={title ? styles.stateDetail : styles.lede}>{children}</p>
        {action ? <div className={styles.stateAction}>{action}</div> : null}
      </div>
    </div>
  );
}

export type StatusTone =
  | "ok"
  | "active"
  | "idle"
  | "attention"
  | "unknown"
  | "danger";

/** A state word with a shape beside it; colour carries state, not decoration. */
export function StatusTag({
  tone,
  children,
  className,
}: {
  tone: StatusTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn(styles.status, className)} data-tone={tone}>
      {children}
    </span>
  );
}

/**
 * Mutually exclusive filters for one list. Toggle buttons in a named group,
 * not tabs: nothing here owns a tab panel, so tab roles would point at
 * panels that do not exist.
 */
export function FilterGroup<T extends string>({
  label,
  value,
  options,
  onChange,
  showLabel = false,
  className,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  showLabel?: boolean;
  className?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(styles.filters, className)}
    >
      {showLabel ? (
        <span
          className={cn(styles.eyebrow, styles.filterLabel)}
          aria-hidden="true"
        >
          {label}
        </span>
      ) : null}
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={styles.filter}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
