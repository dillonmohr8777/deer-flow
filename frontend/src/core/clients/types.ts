export type ClientStatus = "active" | "inactive" | "prospect";

export type ClientAssignment = {
  user_id: string;
  role: "account_manager" | "contributor" | "client_contact";
  created_at: string;
  updated_at: string;
};

/** ``ClientResponse`` (``backend/app/gateway/routers/clients.py``). */
export type Client = {
  id: string;
  display_name: string;
  aliases: string[];
  status: ClientStatus;
  email_domains: string[];
  slack_channel_ids: string[];
  registry_id: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
  assignments: ClientAssignment[];
  project_count: number;
};
