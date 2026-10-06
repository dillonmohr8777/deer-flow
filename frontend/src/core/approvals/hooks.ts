import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  APPROVALS_QUERY_KEY,
  approveApproval,
  editApproval,
  listApprovals,
  rejectApproval,
} from "./api";
import type { Approval, ApprovalEdit, ApprovalStatus } from "./types";

export function useApprovals(status?: ApprovalStatus) {
  return useQuery<Approval[]>({
    queryKey: [...APPROVALS_QUERY_KEY, status ?? null],
    queryFn: () => listApprovals(status),
    enabled: !isStaticWebsiteOnly(),
  });
}

function useApprovalMutation<V>(run: (variables: V) => Promise<Approval>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: APPROVALS_QUERY_KEY }),
  });
}

export function useEditApproval() {
  return useApprovalMutation(
    ({ id, edit }: { id: string; edit: ApprovalEdit }) =>
      editApproval(id, edit),
  );
}

export function useApproveApproval() {
  return useApprovalMutation(({ id }: { id: string }) => approveApproval(id));
}

export function useRejectApproval() {
  return useApprovalMutation(({ id }: { id: string }) => rejectApproval(id));
}
