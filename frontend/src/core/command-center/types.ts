/** ``GET /api/cost-router/spend`` (``backend/app/gateway/routers/cost_router.py``). */
export type SpendRoute = {
  model: string;
  today_usd: number;
  month_usd: number;
  daily_cap_usd: number | null;
  monthly_cap_usd: number | null;
  priced: boolean;
  unpriced_usage: boolean;
};
export type SpendReport = {
  enabled: boolean;
  routes: Record<string, SpendRoute>;
};

type Unavailable = { available: false; reason: string };

/** ``GET /api/command-center/board`` (``backend/app/gateway/routers/command_center.py``). */
export type AdmissionTile =
  | Unavailable
  | {
      available: true;
      as_of: string;
      ceiling_usd: number;
      used_usd: number;
      by_route: Record<string, number>;
    };
export type EvalsTile =
  | Unavailable
  | {
      available: true;
      as_of: string;
      weeks: { week: string; pass_rate: number; runs: number; tasks: number }[];
    };
export type LobbyTile =
  | Unavailable
  | {
      available: true;
      as_of: string | null;
      nodes: { id: string }[];
      edges: { source: string; target: string; score: number }[];
    };
export type BoardData = {
  as_of: string;
  admission: AdmissionTile;
  evals: EvalsTile;
  lobby: LobbyTile;
};
