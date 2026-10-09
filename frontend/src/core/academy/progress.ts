import type { Academy, AcademyTrack } from "./types";

/** A copy of *academy* with one lesson's completion set, counts kept honest. */
export function withLessonCompleted(
  academy: Academy,
  lessonId: string,
  completed: boolean,
): Academy {
  let delta = 0;
  const tracks = academy.tracks.map((track) => ({
    ...track,
    lessons: track.lessons.map((lesson) => {
      if (lesson.id !== lessonId || lesson.completed === completed) {
        return lesson;
      }
      delta += completed ? 1 : -1;
      return { ...lesson, completed };
    }),
  }));
  return {
    ...academy,
    tracks,
    completed_count: academy.completed_count + delta,
  };
}

/** ``{done, total}`` for one track. */
export function trackProgress(track: AcademyTrack): {
  done: number;
  total: number;
} {
  return {
    done: track.lessons.filter((lesson) => lesson.completed).length,
    total: track.lessons.length,
  };
}

/** The first unfinished lesson across all tracks, in order, or null when done. */
export function nextLessonId(academy: Academy): string | null {
  for (const track of academy.tracks) {
    for (const lesson of track.lessons) {
      if (!lesson.completed) return lesson.id;
    }
  }
  return null;
}
