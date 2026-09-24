import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  FLEET_TEMPLATES_QUERY_KEY,
  clientAgentsQueryKey,
  listClientAgents,
  listFleetTemplates,
  stampClientAgent,
} from "./api";
import type { FleetTemplate } from "./types";

export function useFleetTemplates() {
  return useQuery<FleetTemplate[]>({
    queryKey: FLEET_TEMPLATES_QUERY_KEY,
    queryFn: listFleetTemplates,
    // Static-demo mode has no Gateway; never fire this request there.
    enabled: !isStaticWebsiteOnly(),
  });
}

export function useClientAgents(clientId: string | null | undefined) {
  return useQuery({
    queryKey: clientAgentsQueryKey(clientId ?? ""),
    queryFn: () => listClientAgents(clientId!),
    enabled: !isStaticWebsiteOnly() && !!clientId,
  });
}

export function useStampClientAgent(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (templateId: string) => stampClientAgent(clientId, templateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: clientAgentsQueryKey(clientId),
      });
    },
  });
}
