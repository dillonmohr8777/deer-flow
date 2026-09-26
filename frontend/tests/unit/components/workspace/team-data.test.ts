import { describe, expect, it } from "@rstest/core";

import {
  authorLabel,
  canManageChannels,
  displayName,
  formatStamp,
  roleOf,
  startsGroup,
} from "@/components/workspace/team/team-data";
import type { TeamMember, TeamMessage } from "@/core/team";

const members: TeamMember[] = [
  { user_id: "u-owner", email: "dillon@momentum.example", role: "owner" },
  { user_id: "u-member", email: "jesse.d@momentum.example", role: "member" },
];

function message(patch: Partial<TeamMessage>): TeamMessage {
  return {
    id: "m1",
    channel_id: "c1",
    author_user_id: "u-member",
    body: "hi",
    created_at: "2026-09-25T14:00:00Z",
    ...patch,
  };
}

describe("team data", () => {
  it("lets only owners and admins manage channels, matching the API", () => {
    expect(canManageChannels("owner")).toBe(true);
    expect(canManageChannels("admin")).toBe(true);
    expect(canManageChannels("member")).toBe(false);
    expect(canManageChannels("client")).toBe(false);
    expect(canManageChannels(null)).toBe(false);
  });

  it("names authors from the directory, with You and a stable fallback", () => {
    expect(authorLabel("u-member", members, "u-owner")).toBe("jesse.d");
    expect(authorLabel("u-owner", members, "u-owner")).toBe("You");
    expect(authorLabel("u-gone", members, "u-owner")).toBe("Former teammate");
    expect(authorLabel("u-member", undefined, null)).toBe("Former teammate");
    expect(displayName("no-at-sign")).toBe("no-at-sign");
  });

  it("reads the caller's role from the directory", () => {
    expect(roleOf("u-owner", members)).toBe("owner");
    expect(roleOf("u-client", members)).toBeNull();
    expect(roleOf(undefined, members)).toBeNull();
  });

  it("groups consecutive messages by author within five minutes", () => {
    const first = message({ id: "a" });
    expect(startsGroup(first, undefined)).toBe(true);
    expect(
      startsGroup(
        message({ id: "b", created_at: "2026-09-25T14:04:00Z" }),
        first,
      ),
    ).toBe(false);
    expect(
      startsGroup(
        message({ id: "c", created_at: "2026-09-25T14:06:00Z" }),
        first,
      ),
    ).toBe(true);
    expect(
      startsGroup(message({ id: "d", author_user_id: "u-owner" }), first),
    ).toBe(true);
  });

  it("formats stamps and tolerates a bad date", () => {
    const now = new Date("2026-09-25T18:00:00Z");
    expect(formatStamp("not-a-date", now)).toBe("");
    expect(formatStamp("2026-09-20T12:00:00Z", now)).not.toBe("");
  });
});
