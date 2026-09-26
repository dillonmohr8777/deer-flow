import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import { ACADEMY_QUERY_KEY, getAcademy, setLessonCompleted } from "./api";
import { withLessonCompleted } from "./progress";
import type { Academy } from "./types";

export function useAcademy(enabled = true) {
  return useQuery<Academy>({
    queryKey: ACADEMY_QUERY_KEY,
    queryFn: getAcademy,
    enabled: enabled && !isStaticWebsiteOnly(),
  });
}

/** Optimistic: the checkbox flips at once and rolls back if the save fails. */
export function useSetLessonCompleted() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      lessonId,
      completed,
    }: {
      lessonId: string;
      completed: boolean;
    }) => setLessonCompleted(lessonId, completed),
    onMutate: async ({ lessonId, completed }) => {
      await queryClient.cancelQueries({ queryKey: ACADEMY_QUERY_KEY });
      const previous = queryClient.getQueryData<Academy>(ACADEMY_QUERY_KEY);
      if (previous) {
        queryClient.setQueryData(
          ACADEMY_QUERY_KEY,
          withLessonCompleted(previous, lessonId, completed),
        );
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(ACADEMY_QUERY_KEY, context.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ACADEMY_QUERY_KEY });
    },
  });
}
