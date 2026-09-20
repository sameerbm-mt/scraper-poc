import { Badge } from "@/components/ui/badge";
import type { JobStatus } from "@/lib/api";

const VARIANT: Record<
  JobStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  queued: "outline",
  running: "secondary",
  // The in-between states read as "something is happening", like running.
  pausing: "secondary",
  paused: "outline",
  resuming: "secondary",
  completed: "default",
  failed: "destructive",
  // Cancelling is a decision, not a fault — it should not look like an error.
  cancelled: "outline",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return <Badge variant={VARIANT[status]}>{status}</Badge>;
}
