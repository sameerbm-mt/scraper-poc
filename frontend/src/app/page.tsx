"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { CrawlForm } from "@/components/crawl-form";
import { JobStatusCard } from "@/components/job-status-card";
import { PageDetailSheet } from "@/components/page-detail-sheet";
import { ResultsTable } from "@/components/results-table";
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
  const [resultsPage, setResultsPage] = useState(1);
  const [resultsLoading, setResultsLoading] = useState(false);
  const [profile, setProfile] = useState<SiteProfile | null>(null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [detail, setDetail] = useState<PageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Lets the poller notice a status change without re-subscribing every tick.
  const previousStatus = useRef<string | null>(null);

  const jobId = job?.job_id ?? null;
  const polling = job !== null && !isTerminal(job.status);

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
      setResultsPage(1);
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

  // Poll the job while it is queued or running.
  useEffect(() => {
    if (!jobId || !polling) return;

    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const next = await getJob(jobId);
        if (cancelled) return;
        setJob(next);

        // Refresh the table as pages land, and once more when the job ends.
        if (next.pages_crawled !== job?.pages_crawled || isTerminal(next.status)) {
          void loadResults(jobId, resultsPage);
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
  }, [jobId, polling, resultsPage, job?.pages_crawled, loadResults]);

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
    setResultsPage(page);
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
    <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          Website crawler
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Scrapy + ARQ + FastAPI. Crawls every page of a site, extracts
          markdown, and writes JSONL + CSV per job alongside MongoDB.
        </p>
      </header>

      <div className="grid gap-6">
        <CrawlForm onSubmit={handleSubmit} disabled={submitting || polling} />

        {job ? (
          <>
            <JobStatusCard job={job} />
            {profile ? <SiteProfileCard profile={profile} /> : null}
            <ResultsTable
              results={results}
              loading={resultsLoading}
              onSelect={handleSelect}
              onPageChange={handlePageChange}
            />
          </>
        ) : null}
      </div>

      <PageDetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        detail={detail}
        loading={detailLoading}
        error={detailError}
      />
    </main>
  );
}
