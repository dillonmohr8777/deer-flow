/**
 * The client (external customer) version of MomoBot.
 *
 * A `client` user gets chat with the built-in agent, plus the agents of their
 * own dedicated workspace when the Gateway lists them, and nothing else. This
 * module is convenience only: the Gateway's client route boundary and the role
 * policy are the real guard, and answer 403 to every other route.
 */

export const CLIENT_AGENT_NAME = "momobot-max";
/** A client's "new chat" entry: `RoleRouteGuard` resolves it to their agent once the agents list is in. */
export const CLIENT_NEW_CHAT_PATH = "/workspace/chats/new";

/** Where a client's new chat starts: their workspace's own agent when the Gateway lists one, else MomoBot Max. */
export function clientNewChatPath(
  agents: readonly { name: string; builtin?: boolean }[],
) {
  const own = agents.find((agent) => agent.builtin === false);
  return `/workspace/agents/${own?.name ?? CLIENT_AGENT_NAME}/chats/new`;
}

export function isClientUser(
  user: { system_role?: string } | null | undefined,
) {
  return user?.system_role === "client";
}

/**
 * True while there is no signed-in user to read a role from (loading, or
 * mid-logout). Internal UI must render nothing then: the user may turn out to
 * be a client. A static website has no sign-in, so it is never unresolved.
 */
export function isRoleUnresolved(
  user: { system_role?: string } | null | undefined,
  staticMode: boolean,
) {
  return !staticMode && !user;
}

/** Workspace pages a client may open. Everything else shows "not available". */
const CLIENT_PATHS: readonly RegExp[] = [
  /^\/workspace\/inbox$/,
  // The chat list and existing chats. `/workspace/chats/new` is not here: it
  // would start a chat with the default agent, so it redirects instead.
  /^\/workspace\/chats$/,
  /^\/workspace\/chats\/(?!new$)[^/]+$/,
  // Any agent: the Gateway answers 404 for one that is not the client's.
  /^\/workspace\/agents\/[^/]+\/chats\/[^/]+$/,
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
