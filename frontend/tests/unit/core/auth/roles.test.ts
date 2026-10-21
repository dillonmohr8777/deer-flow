import { describe, expect, it } from "@rstest/core";

import {
  CLIENT_AGENT_NAME,
  CLIENT_NEW_CHAT_PATH,
  CLIENT_SETTINGS_SECTIONS,
  isClientPath,
  isClientUser,
  isRoleUnresolved,
} from "@/core/auth/roles";
import { SYSTEM_ROLES, userSchema } from "@/core/auth/types";
import { isOpenAIAgentsConfigured } from "@/core/features";

const base = { id: "u1", email: "u@example.test" };

describe("system roles", () => {
  it("accepts the four roles the Gateway can return", () => {
    expect([...SYSTEM_ROLES]).toEqual(["admin", "exec", "user", "client"]);
    for (const role of SYSTEM_ROLES) {
      expect(userSchema.parse({ ...base, system_role: role }).system_role).toBe(
        role,
      );
    }
  });

  it("rejects a role it does not know, so an unknown role never signs in", () => {
    for (const role of ["superuser", "Admin", "owner", ""]) {
      expect(userSchema.safeParse({ ...base, system_role: role }).success).toBe(
        false,
      );
    }
  });

  it("recognises only a client as a client", () => {
    expect(isClientUser({ system_role: "client" })).toBe(true);
    for (const role of ["admin", "exec", "user"]) {
      expect(isClientUser({ system_role: role })).toBe(false);
    }
    expect(isClientUser(null)).toBe(false);
    expect(isClientUser(undefined)).toBe(false);
  });
});

describe("client pages", () => {
  it("opens chats, a chat with MomoBot Max, the lineup and About", () => {
    for (const path of [
      "/workspace/chats",
      "/workspace/chats/",
      "/workspace/chats/abc-123",
      `/workspace/agents/${CLIENT_AGENT_NAME}/chats/new`,
      `/workspace/agents/${CLIENT_AGENT_NAME}/chats/abc-123`,
      "/workspace/lineup",
      "/workspace/about",
    ]) {
      expect(isClientPath(path), path).toBe(true);
    }
    expect(isClientPath(CLIENT_NEW_CHAT_PATH)).toBe(true);
  });

  it("closes every internal page", () => {
    for (const path of [
      "/workspace",
      "/workspace/command-center",
      "/workspace/approvals",
      "/workspace/board",
      "/workspace/desk",
      "/workspace/desk/agent-room",
      "/workspace/team",
      "/workspace/academy",
      "/workspace/openai",
      "/workspace/workflows",
      "/workspace/browser-research",
      "/workspace/agents",
      "/workspace/agents/new",
      "/workspace/agents/some-other-agent/chats/new",
      "/workspace/agents/momobot-max",
      "/workspace/scheduled-tasks",
      "/workspace/capabilities",
      "/workspace/projects/p1",
      "/workspace/trash",
      "/workspace/extensions/anything",
      "/daily",
    ]) {
      expect(isClientPath(path), path).toBe(false);
    }
  });

  it("sends a new default chat to MomoBot Max instead of opening it", () => {
    expect(isClientPath("/workspace/chats/new")).toBe(false);
    expect(CLIENT_NEW_CHAT_PATH).toBe(
      "/workspace/agents/momobot-max/chats/new",
    );
  });

  it("keeps account, appearance and About in Settings and nothing admin", () => {
    expect([...CLIENT_SETTINGS_SECTIONS].sort()).toEqual([
      "about",
      "account",
      "appearance",
      "notification",
      "security",
    ]);
  });
});

describe("OpenAI crew availability", () => {
  it("is on only when the Gateway says it is configured", () => {
    expect(isOpenAIAgentsConfigured({ agents_api: { enabled: true } })).toBe(
      false,
    );
    expect(
      isOpenAIAgentsConfigured({
        agents_api: { enabled: true },
        openai_agents: { configured: false },
      }),
    ).toBe(false);
    expect(
      isOpenAIAgentsConfigured({
        agents_api: { enabled: true },
        openai_agents: {},
      }),
    ).toBe(false);
    expect(
      isOpenAIAgentsConfigured({
        agents_api: { enabled: true },
        openai_agents: { configured: true },
      }),
    ).toBe(true);
  });
});

describe("unresolved role", () => {
  it("is unresolved while there is no user, so internal UI waits", () => {
    expect(isRoleUnresolved(null, false)).toBe(true);
    expect(isRoleUnresolved(undefined, false)).toBe(true);
  });

  it("is resolved for every signed-in role and for a static website", () => {
    for (const role of ["admin", "exec", "user", "client"]) {
      expect(isRoleUnresolved({ system_role: role }, false)).toBe(false);
    }
    expect(isRoleUnresolved(null, true)).toBe(false);
  });
});
