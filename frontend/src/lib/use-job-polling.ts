"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { errorMessage, getJob, isTerminal, type JobState } from "@/lib/api";

const POLL_INTERVAL_MS = 2000;

/**
 * Keep `job` fresh while it is queued or running.
 *
 * Polls GET /api/jobs/{id} every 2 s and hands each response to `onUpdate`. It
 * stops by itself once the job reaches a terminal status, and does nothing for a
 * job that is already finished. `onUpdate` may change on every render.
 */
export function useJobPolling(
  job: JobState | null,
  onUpdate: (job: JobState) => void,
): void {
  const jobId = job?.job_id ?? null;
  const active = job !== null && !isTerminal(job.status);

  const latestOnUpdate = useRef(onUpdate);
  useEffect(() => {
    latestOnUpdate.current = onUpdate;
  });

  useEffect(() => {
    if (!jobId || !active) return;

    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const next = await getJob(jobId);
        if (!cancelled) latestOnUpdate.current(next);
      } catch (error) {
        if (!cancelled) {
          toast.error("Lost contact with the API", {
            description: errorMessage(error),
          });
        }
      }
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, active]);
}
