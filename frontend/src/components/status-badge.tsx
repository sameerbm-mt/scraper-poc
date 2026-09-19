import { Badge } from "@/components/ui/badge";
import type { JobStatus } from "@/lib/api";

const VARIANT: Record<
  JobStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  queued: "outline",
  running: "secondary",
  completed: "default",
  failed: "destructive",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge variant={VARIANT[status]}>{status}</Badge>;
}
