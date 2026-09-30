export type AgentRoomMessageType =
  | "instruction"
  | "note"
  | "progress"
  | "finding"
  | "deliverable"
  | "handoff"
  | "question";

export interface AgentRoomMessage {
  id: string;
  user_id: string;
  author_kind: "owner" | "agent";
  agent_id: string | null;
  agent_role: string;
  message_type: AgentRoomMessageType;
  body: string;
  run_id: string | null;
  created_at: string;
}

export interface AgentRoomRole {
  id: string;
  name: string;
  focus: string;
  model: string;
}

export const AGENT_ROOM_ROLES: AgentRoomRole[] = [
  {
    id: "room-coordinator",
    name: "Coordinator",
    focus:
      "Breaks Momentum work into small assignments and synthesizes results.",
    model: "Muse Spark 1.3 Contributor",
  },
  {
    id: "momentum-research",
    name: "Momentum Research",
    focus:
      "Finds and verifies current Momentum problems, project status, and source material.",
    model: "GPT-6 Luna Max",
  },
  {
    id: "prospect-research",
    name: "Prospect Research",
    focus:
      "Researches public business contact details and prepares source-backed outreach drafts.",
    model: "GPT-6 Luna Max",
  },
  {
    id: "web-quality",
    name: "Web Quality",
    focus:
      "Finds website defects and prepares reviewable fixes without publishing.",
    model: "GPT-6 Luna Max",
  },
  {
    id: "client-operations",
    name: "Client Operations",
    focus:
      "Tracks deliverables and blockers; keeps client communication drafts in the room.",
    model: "GPT-6 Luna Max",
  },
  {
    id: "independent-reviewer",
    name: "Independent Reviewer",
    focus:
      "Checks evidence, identifies unsupported claims, and reviews agent handoffs.",
    model: "GPT-6 Luna Max",
  },
];
