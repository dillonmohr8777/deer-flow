import { CeoDesk } from "@/components/workspace/ceo-desk/ceo-desk";

// No static metadata: the title is set only once the flag says the CEO
// Desk exists, so a plain member or client never sees it named.
export default function CeoDeskPage() {
  return <CeoDesk />;
}
