import type { TeamMember, TeamMessage } from "@/core/team";

/** Channel management is owner/admin only; the backend enforces the same rule. */
export function canManageChannels(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

/** "dillon.mohr@momentum.example" reads as "dillon.mohr". */
export function displayName(email: string): string {
  const local = email.split("@")[0] ?? "";
  return local || email;
}

/**
 * Name a message's author from the staff directory. Someone who has left
 * the workspace (no longer listed) still gets a stable, non-empty label.
 */
export function authorLabel(
  authorUserId: string,
  members: readonly TeamMember[] | undefined,
  currentUserId: string | null | undefined,
): string {
  if (currentUserId && authorUserId === currentUserId) return "You";
  const member = members?.find((m) => m.user_id === authorUserId);
  return member ? displayName(member.email) : "Former teammate";
}

/** The caller's own role, from the staff directory. */
export function roleOf(
  userId: string | null | undefined,
  members: readonly TeamMember[] | undefined,
): string | null {
  if (!userId) return null;
  return members?.find((m) => m.user_id === userId)?.role ?? null;
}

/**
 * Whether *message* starts a new visual group: a different author than the
 * one before it, or more than five minutes later.
 */
export function startsGroup(
  message: TeamMessage,
  previous: TeamMessage | undefined,
): boolean {
  if (!previous) return true;
  if (previous.author_user_id !== message.author_user_id) return true;
  const gap = Date.parse(message.created_at) - Date.parse(previous.created_at);
  return !(gap >= 0 && gap <= 5 * 60 * 1000);
}

/** Short, locale-aware time for a message stamp; empty for a bad date. */
export function formatStamp(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}
