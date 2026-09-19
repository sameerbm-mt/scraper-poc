"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";

import { CrawlForm } from "@/components/crawl-form";
import { JobResults } from "@/components/job-results";
import { JobStatusCard } from "@/components/job-status-card";
import { SiteProfileCard } from "@/components/site-profile-card";
import {
  errorMessage,
  getJob,
  getJobSite,
  isTerminal,
  startCrawl,
  type CrawlRequest,
  type JobState,
  type SiteProfile,
} from "@/lib/api";
import { useJobPolling } from "@/lib/use-job-polling";

export default function Home() {
  const [job, setJob] = useState<JobState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState<SiteProfile | null>(null);

  // The status whose "finished" / "failed" toast has already been shown.
  const announced = useRef<string | null>(null);

  const polling = job !== null && !isTerminal(job.status);
  const finished = job !== null && isTerminal(job.status);

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
    } else {
      toast.error("Crawl failed", {
        description: next.error?.split("\n")[0] ?? "See the job status for details",
      });
    }
  }

  // Poll while the job is queued or running; the results load once it finishes.
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
            <JobStatusCard job={job} />
            {profile ? <SiteProfileCard profile={profile} /> : null}
            {finished ? <JobResults key={job.job_id} jobId={job.job_id} /> : null}
          </>
        ) : null}
      </div>
    </main>
  );
}
