export type FleetTemplateSchedule = {
  cron: string;
  timezone: string;
};

/** ``FleetTemplateResponse`` (``backend/app/gateway/routers/fleet.py``). */
export type FleetTemplate = {
  id: string;
  version: string;
  name: string;
  description: string;
  model: string;
  skills: string[];
  tool_groups: string[];
  mcp_plugins: string[];
  schedule: FleetTemplateSchedule;
  acceptance_criteria: string[];
};

/** ``FleetAgentBindingResponse`` (``backend/app/gateway/routers/clients.py``). */
export type FleetAgentBinding = {
  client_id: string;
  template_id: string;
  template_version: string;
  agent_name: string;
  display_name: string | null;
  description: string | null;
  scheduled_task_id: string | null;
  created_at: string;
  updated_at: string;
};
