import { useQuery } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import { CLIENTS_QUERY_KEY, listClients } from "./api";
import type { Client } from "./types";

export function useClients({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery<Client[]>({
    queryKey: CLIENTS_QUERY_KEY,
    queryFn: listClients,
    // Static-demo mode has no Gateway; never fire client requests there.
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}
