/**
 * The client (external customer) version of MomoBot.
 *
 * A `client` user gets chat with one built-in agent and nothing else. This
 * module is convenience only: the Gateway's client route boundary and the role
 * policy are the real guard, and answer 403 to every other route.
 */

export const CLIENT_AGENT_NAME = "momobot-max";
export const CLIENT_NEW_CHAT_PATH = `/workspace/agents/${CLIENT_AGENT_NAME}/chats/new`;

export function isClientUser(
  user: { system_role?: string } | null | undefined,
) {
  return user?.system_role === "client";
}

/** Workspace pages a client may open. Everything else shows "not available". */
const CLIENT_PATHS: readonly RegExp[] = [
  // The chat list and existing chats. `/workspace/chats/new` is not here: it
  // would start a chat with the default agent, so it redirects instead.
  /^\/workspace\/chats$/,
  /^\/workspace\/chats\/(?!new$)[^/]+$/,
  new RegExp(`^/workspace/agents/${CLIENT_AGENT_NAME}/chats/[^/]+$`),
  /^\/workspace\/lineup$/,
  /^\/workspace\/about$/,
];

export function isClientPath(pathname: string) {
  const path = pathname.replace(/\/+$/, "") || "/";
  return CLIENT_PATHS.some((pattern) => pattern.test(path));
}

/** Settings sections a client sees; the rest are internal or admin tools. */
export const CLIENT_SETTINGS_SECTIONS: ReadonlySet<string> = new Set([
  "account",
  "security",
  "appearance",
  "notification",
  "about",
]);
