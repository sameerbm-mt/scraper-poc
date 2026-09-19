"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { CrawlForm } from "@/components/crawl-form";
import { JobStatusCard } from "@/components/job-status-card";
import { PageDetailSheet } from "@/components/page-detail-sheet";
import { ResultsTable } from "@/components/results-table";
import { SiteFooter, SiteHeader } from "@/components/site-header";
import { SiteProfileCard } from "@/components/site-profile-card";
import {
  ApiError,
  getJob,
  getJobSite,
  getResult,
  getResults,
  isTerminal,
  startCrawl,
  type CrawlRequest,
  type JobState,
  type PageDetail,
  type PageSummary,
  type ResultsPage,
  type SiteProfile,
} from "@/lib/api";

const POLL_INTERVAL_MS = 2000;
const PAGE_SIZE = 20;

const EMPTY_RESULTS: ResultsPage = {
  items: [],
  page: 1,
  size: PAGE_SIZE,
  total: 0,
  total_pages: 0,
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : "Something went wrong";
}

export default function Home() {
  const [job, setJob] = useState<JobState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [results, setResults] = useState<ResultsPage>(EMPTY_RESULTS);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [profile, setProfile] = useState<SiteProfile | null>(null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [detail, setDetail] = useState<PageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Guards the one-shot "crawl finished/failed" handling against re-renders.
  const previousStatus = useRef<string | null>(null);

  const jobId = job?.job_id ?? null;
  const polling = job !== null && !isTerminal(job.status);
  const finished = job !== null && isTerminal(job.status);

  const loadResults = useCallback(async (id: string, page: number) => {
    setResultsLoading(true);
    try {
      setResults(await getResults(id, page, PAGE_SIZE));
    } catch (error) {
      toast.error("Could not load results", {
        description: errorMessage(error),
      });
    } finally {
      setResultsLoading(false);
    }
  }, []);

  async function handleSubmit(request: CrawlRequest) {
    setSubmitting(true);
    try {
      const { job_id: newJobId } = await startCrawl(request);
      previousStatus.current = null;
      setResults(EMPTY_RESULTS);
      setProfile(null);
      setJob(await getJob(newJobId));
      toast.success("Crawl started", { description: request.url });
    } catch (error) {
      toast.error("Could not start the crawl", {
        description: errorMessage(error),
      });
    } finally {
      setSubmitting(false);
    }
  }

  // Poll the job while it is queued or running. Results are not fetched here:
  // they load once, the moment the crawl has finished.
  useEffect(() => {
    if (!jobId || !polling) return;

    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const next = await getJob(jobId);
        if (cancelled) return;
        setJob(next);
        // The crawl just ended: fetch the first page of results.
        if (isTerminal(next.status) && next.pages_crawled > 0) {
          void loadResults(jobId, 1);
        }
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
  }, [jobId, polling, loadResults]);

  // Announce the terminal status once.
  useEffect(() => {
    if (!job || !isTerminal(job.status)) return;
    if (previousStatus.current === job.status) return;
    previousStatus.current = job.status;

    if (job.status === "completed") {
      toast.success(`Crawl finished — ${job.pages_crawled} pages`);
      // Mongo only has the profile once the spider has closed.
      getJobSite(job.job_id)
        .then(setProfile)
        .catch(() => setProfile(null));
    } else {
      toast.error("Crawl failed", {
        description: job.error?.split("\n")[0] ?? "See the job status for details",
      });
    }
  }, [job]);

  function handlePageChange(page: number) {
    if (!jobId) return;
    void loadResults(jobId, page);
  }

  async function handleSelect(item: PageSummary) {
    if (!jobId) return;
    setSheetOpen(true);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      setDetail(await getResult(jobId, item.index));
    } catch (error) {
      setDetailError(errorMessage(error));
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <>
      <SiteHeader />

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
              {finished ? (
                <ResultsTable
                  results={results}
                  loading={resultsLoading}
                  onSelect={handleSelect}
                  onPageChange={handlePageChange}
                />
              ) : null}
            </>
          ) : null}
        </div>
      </main>

      <SiteFooter />

      <PageDetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        detail={detail}
        loading={detailLoading}
        error={detailError}
      />
    </>
  );
}
