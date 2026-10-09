/** Mirrors ``app.gateway.routers.team_board``'s response models. */

export interface TeamChannel {
  id: string;
  slug: string;
  name: string;
  topic: string;
  created_at: string;
}

export interface TeamMessage {
  id: string;
  channel_id: string;
  author_user_id: string;
  body: string;
  created_at: string;
}

export interface TeamMember {
  user_id: string;
  email: string;
  role: string;
}
