import { describe, expect, it } from "@rstest/core";

import {
  nextLessonId,
  trackProgress,
  withLessonCompleted,
  type Academy,
  type AcademyLesson,
} from "@/core/academy";

function lesson(id: string, completed = false): AcademyLesson {
  return {
    id,
    title: id,
    minutes: 5,
    summary: "",
    steps: ["step"],
    try_it: "try",
    video_slot: null,
    video_url: null,
    completed,
  };
}

const academy: Academy = {
  tracks: [
    {
      id: "t1",
      title: "T1",
      summary: "",
      lessons: [lesson("a", true), lesson("b")],
    },
    { id: "t2", title: "T2", summary: "", lessons: [lesson("c")] },
  ],
  completed_count: 1,
  lesson_count: 3,
};

describe("academy progress", () => {
  it("marks a lesson and keeps the count honest", () => {
    const next = withLessonCompleted(academy, "b", true);
    expect(next.completed_count).toBe(2);
    expect(next.tracks[0]!.lessons[1]!.completed).toBe(true);
    // The input is not mutated.
    expect(academy.tracks[0]!.lessons[1]!.completed).toBe(false);
  });

  it("is a no-op for an unchanged or unknown lesson", () => {
    expect(withLessonCompleted(academy, "a", true).completed_count).toBe(1);
    expect(withLessonCompleted(academy, "zzz", true).completed_count).toBe(1);
    expect(withLessonCompleted(academy, "a", false).completed_count).toBe(0);
  });

  it("reports per-track progress and the next unfinished lesson", () => {
    expect(trackProgress(academy.tracks[0]!)).toEqual({ done: 1, total: 2 });
    expect(nextLessonId(academy)).toBe("b");
    const allDone = withLessonCompleted(
      withLessonCompleted(academy, "b", true),
      "c",
      true,
    );
    expect(nextLessonId(allDone)).toBeNull();
  });
});
