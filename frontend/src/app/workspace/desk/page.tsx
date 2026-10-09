import { Desk } from "@/components/workspace/desk/desk";

// No static metadata: the title is set only once the flag says Desk exists,
// so a client-facing instance never names it.
export default function DeskPage() {
  return <Desk />;
}
