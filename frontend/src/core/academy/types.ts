/** Mirrors ``app.gateway.routers.academy``'s response models. */

export interface AcademyLesson {
  id: string;
  title: string;
  minutes: number;
  summary: string;
  steps: string[];
  try_it: string;
  video_slot: string | null;
  video_url: string | null;
  completed: boolean;
}

export interface AcademyTrack {
  id: string;
  title: string;
  summary: string;
  lessons: AcademyLesson[];
}

export interface Academy {
  tracks: AcademyTrack[];
  completed_count: number;
  lesson_count: number;
}
