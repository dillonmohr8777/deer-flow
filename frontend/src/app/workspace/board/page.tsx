import { Board } from "@/components/workspace/board/board";

// No static metadata: the title is set only once the flag says Board
// exists, so a client-facing instance never names it.
export default function BoardPage() {
  return <Board />;
}
