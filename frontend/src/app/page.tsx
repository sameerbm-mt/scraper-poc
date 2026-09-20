"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";

import { CrawlForm } from "@/components/crawl-form";
import { JobResults } from "@/components/job-results";
import { JobStatsCard } from "@/components/job-stats-card";
import { JobStatusCard, type JobAction } from "@/components/job-status-card";
import { SiteProfileCard } from "@/components/site-profile-card";
import {
  cancelJob,
  errorMessage,
  getJob,
  getJobSite,
  isTerminal,
  pauseJob,
  resumeJob,
  startCrawl,
  type CrawlRequest,
  type JobState,
  type SiteProfile,
} from "@/lib/api";
import { useJobPolling } from "@/lib/use-job-polling";

const ACTIONS: Record<
  JobAction,
  { run: (jobId: string) => Promise<JobState>; done: string }
> = {
  pause: { run: pauseJob, done: "Pausing — finishing the requests in flight" },
  resume: { run: resumeJob, done: "Resuming from the saved queue" },
  cancel: { run: cancelJob, done: "Cancelling — partial results are kept" },
};

export default function Home() {
  const [job, setJob] = useState<JobState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState<SiteProfile | null>(null);
  const [pending, setPending] = useState<JobAction | null>(null);

  // The status whose terminal toast has already been shown.
  const announced = useRef<string | null>(null);

  const polling = job !== null && !isTerminal(job.status);
  const finished = job !== null && isTerminal(job.status);
  // Results and stats are worth showing the moment there is anything to show,
  // not only at the end: a paused or cancelled crawl has real output too.
  const hasOutput = job !== null && job.pages_crawled > 0;

  function handleUpdate(next: JobState) {
    setJob(next);
    if (!isTerminal(next.status) || announced.current === next.status) return;
    announced.current = next.status;

    if (next.status === "completed") {
      toast.success(`Crawl finished — ${next.pages_crawled} pages`);
      // Mongo only has the profile once the spider has closed.
      getJobSite(next.job_id)
        .then(setProfile)
        .catch(() => setProfile(null));
    } else if (next.status === "cancelled") {
      toast.info(`Crawl cancelled — ${next.pages_crawled} pages kept`);
    } else {
      toast.error("Crawl failed", {
        description: next.error?.split("\n")[0] ?? "See the job status for details",
      });
    }
  }

  // Poll while the job is queued, running, pausing, paused or resuming.
  useJobPolling(job, handleUpdate);

  async function handleSubmit(request: CrawlRequest) {
    setSubmitting(true);
    try {
      const { job_id: newJobId } = await startCrawl(request);
      announced.current = null;
      setProfile(null);
      handleUpdate(await getJob(newJobId));
      toast.success("Crawl started", { description: request.url });
    } catch (error) {
      toast.error("Could not start the crawl", {
        description: errorMessage(error),
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAction(action: JobAction) {
    if (!job) return;
    setPending(action);
    try {
      const next = await ACTIONS[action].run(job.job_id);
      // A resume re-opens the job, so the terminal toast may fire again later.
      announced.current = null;
      setJob(next);
      toast.success(ACTIONS[action].done);
    } catch (error) {
      // A 409 here means the job moved on between the render and the click.
      toast.error(`Could not ${action} the crawl`, {
        description: errorMessage(error),
      });
      // Re-read the truth rather than leaving stale buttons on screen.
      try {
        setJob(await getJob(job.job_id));
      } catch {
        // The status card keeps what it had; polling will catch up.
      }
    } finally {
      setPending(null);
    }
  }

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
      <section className="mb-8 max-w-2xl sm:mb-10">
        <span className="bg-accent text-accent-foreground ring-primary/20 inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ring-1">
          Crawl · Extract · Profile
        </span>
        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-balance sm:text-4xl lg:text-5xl">
          Turn any website into{" "}
          <span className="text-primary">structured content</span>
        </h1>
        <p className="text-muted-foreground mt-3 text-sm leading-relaxed text-pretty sm:mt-4 sm:text-base">
          MyraCrawl follows every internal link on a site, extracts each page
          as clean markdown, and builds a profile of the company behind it —
          services, people, and contact details included.
        </p>
      </section>

      <div className="grid gap-5 sm:gap-6">
        <CrawlForm onSubmit={handleSubmit} disabled={submitting || polling} />

        {job ? (
          <>
            <JobStatusCard
              job={job}
              onAction={handleAction}
              pending={pending}
            />
            {hasOutput ? (
              <JobStatsCard
                jobId={job.job_id}
                refreshKey={job.pages_crawled}
              />
            ) : null}
            {profile ? <SiteProfileCard profile={profile} /> : null}
            {hasOutput ? (
              <JobResults
                key={job.job_id}
                jobId={job.job_id}
                // Reload the table as the crawl stores more pages.
                refreshKey={finished ? 0 : job.pages_crawled}
              />
            ) : null}
          </>
        ) : null}
      </div>
    </main>
  );
}
