import { TeamBoard } from "@/components/workspace/team/team-board";

// No static metadata: the title is set only once the flag says Team exists,
// so a client-facing instance never names it.
export default function TeamPage() {
  return <TeamBoard />;
}
