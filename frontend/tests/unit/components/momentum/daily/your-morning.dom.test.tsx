import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRouter } from "next/navigation";

import { YourMorning } from "@/components/momentum/daily/your-morning";
import type { TodayBrief } from "@/core/briefs";
import { useTodayBrief } from "@/core/briefs";
import type { TodayBriefState } from "@/core/briefs/use-today-brief";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  buildComposerDraftKey,
  getSessionComposerDraftStorage,
} from "@/core/threads/composer-draft";

// Hoisted above these imports regardless of source position (rstest mirrors
// Vitest's vi.mock), so `YourMorning`'s own module graph sees the fakes.
rs.mock("@/core/briefs", () => ({ useTodayBrief: rs.fn() }));
rs.mock("next/navigation", () => ({ useRouter: rs.fn() }));

const push = rs.fn();
const copy = enUS.dailyBrief;

const EMPTY_BRIEF: TodayBrief = {
  generated_at: "2026-09-23T12:00:00Z",
  assigned_clients: [],
  activity: [],
  due_today: [],
  waiting_on_you: [],
};

function mockBrief(state: TodayBriefState) {
  rs.mocked(useTodayBrief).mockReturnValue(state);
}

beforeEach(() => {
  push.mockReset();
  rs.mocked(useTodayBrief).mockReset();
  rs.mocked(useRouter)
    .mockReset()
    .mockReturnValue({ push } as unknown as ReturnType<typeof useRouter>);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
});

describe("YourMorning", () => {
  it("renders nothing for a signed-out visitor (the Daily is public)", () => {
    mockBrief({ status: "loading" });
    const { container } = render(
      <YourMorning signedIn={false} userId={null} copy={copy} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows a loading line while the brief is in flight", () => {
    mockBrief({ status: "loading" });
    render(<YourMorning signedIn userId="user-a" copy={copy} />);
    expect(screen.getByText(copy.loading)).toBeTruthy();
  });

  it("shows an error line when the brief fails to load", () => {
    mockBrief({ status: "error" });
    render(<YourMorning signedIn userId="user-a" copy={copy} />);
    expect(screen.getByText(copy.error)).toBeTruthy();
  });

  it("reads naturally when nothing moved overnight", () => {
    mockBrief({ status: "ready", brief: EMPTY_BRIEF });
    render(<YourMorning signedIn userId="user-a" copy={copy} />);
    expect(
      screen.getByText(`${copy.emptyTitle} ${copy.emptyBody}`),
    ).toBeTruthy();
    expect(screen.queryByText(copy.waitingHeading)).toBeNull();
  });

  it("lists clients, activity, due-today, and waiting items with working links", () => {
    const brief: TodayBrief = {
      generated_at: "2026-09-23T12:00:00Z",
      assigned_clients: [{ id: "c1", display_name: "Acme" }],
      activity: [
        {
          kind: "run_failed",
          title: "Kickoff chat",
          detail: "Boom",
          project_id: "p1",
          project_name: "Acme Website",
          client_id: "c1",
          client_name: "Acme",
          thread_id: "t1",
          agent_name: null,
          occurred_at: "2026-09-23T11:00:00Z",
        },
      ],
      due_today: [
        {
          task_id: "task-1",
          title: "Weekly digest",
          next_run_at: "2026-09-23T20:00:00Z",
          thread_id: null,
        },
      ],
      waiting_on_you: [
        {
          kind: "interrupted",
          thread_id: "t2",
          run_id: "r2",
          title: "Blocked chat",
          project_id: "p1",
          project_name: "Acme Website",
          client_id: "c1",
          client_name: "Acme",
          agent_name: null,
          updated_at: "2026-09-23T07:00:00Z",
        },
      ],
    };
    mockBrief({ status: "ready", brief });
    render(<YourMorning signedIn userId="user-a" copy={copy} />);

    // "Acme" appears three times: the clients summary line, and once as the
    // client_name meta on each of the activity and waiting rows below.
    expect(screen.getAllByText("Acme")).toHaveLength(3);
    expect(screen.getByText(copy.waitingHeading)).toBeTruthy();
    expect(screen.getByText(copy.dueHeading)).toBeTruthy();
    expect(screen.getByText(copy.activityHeading)).toBeTruthy();

    const threadLink = screen.getByText("Kickoff chat").closest("a");
    expect(threadLink?.getAttribute("href")).toBe("/workspace/chats/t1");
    expect(screen.getByText("Boom")).toBeTruthy();

    const waitingLink = screen.getByText("Blocked chat").closest("a");
    expect(waitingLink?.getAttribute("href")).toBe("/workspace/chats/t2");
    expect(screen.getByText(copy.waitingInterrupted)).toBeTruthy();

    expect(screen.getByText("Weekly digest")).toBeTruthy();
  });

  it("pre-fills a new chat and navigates when 'Have Momo write it up' is clicked", () => {
    const brief: TodayBrief = {
      ...EMPTY_BRIEF,
      assigned_clients: [{ id: "c1", display_name: "Acme" }],
    };
    mockBrief({ status: "ready", brief });
    render(<YourMorning signedIn userId="user-a" copy={copy} />);

    fireEvent.click(screen.getByText(copy.writeItUp));

    expect(push).toHaveBeenCalledWith("/workspace/chats/new");
    const key = buildComposerDraftKey({
      userId: "user-a",
      agentName: null,
      threadId: "new",
    });
    const raw = getSessionComposerDraftStorage()?.getItem(key);
    expect(raw).toBeTruthy();
    const draft = JSON.parse(raw!) as { text: string };
    expect(draft.text).toContain(copy.writeItUpIntro);
    expect(draft.text).toContain("Acme");
  });
});
