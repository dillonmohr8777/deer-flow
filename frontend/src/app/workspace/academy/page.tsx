import { AcademyPage } from "@/components/workspace/academy/academy";

// No static metadata: the title is set only once the flag says the Academy
// exists, so a client-facing instance never names it.
export default function Page() {
  return <AcademyPage />;
}
